# StayHub sandbox deployment

Target: account **762079300828**, **us-east-1**, CLI profile **stayhub**. This replaces the old-account infrastructure source by user request; it does not delete old AWS resources. No agent-run AWS apply. Existing sandbox resources with matching names must be imported rather than overwritten/recreated in another state.

## Architecture

One Amazon Linux 2023 x86 EC2 (`t3.small`, 2 GiB) with encrypted 20 GiB gp3 disk and Elastic IP. Nginx serves React and proxies `/api/` to the Unix-socket-only FastAPI container. Worker uses the same backend image. No SSH ingress, ALB, NAT, CloudFront, local Postgres or RustFS in deployment. Single-AZ RDS PostgreSQL 18 (`db.t4g.micro`, 20 GiB) is private; only the EC2 security group can reach it. Private S3 stores photos and release artifacts. GitHub OIDC can deploy only main from `jigar225/stayhub` with the previously supplied immutable owner/repository IDs. Update this trust subject if the repository is moved or workflow uses a GitHub environment.

Terraform provisions network, RDS, ECR, S3, IAM/OIDC, EC2 bootstrap, SSM document and deployment outputs. GitHub publishes releases; no credentials are sent from GitHub to EC2. EC2 obtains temporary IAM credentials through IMDSv2; Docker hop limit is 2. Backend IAM mode is explicitly enabled in deployment only. AWS service endpoints remain publicly reachable for instance egress; the database subnets have no internet route.

## 1. Bootstrap remote state (user runs)

```sh
aws sso login --profile stayhub
aws sts get-caller-identity --profile stayhub
AWS_PROFILE=stayhub terraform -chdir=infra/bootstrap init
AWS_PROFILE=stayhub terraform -chdir=infra/bootstrap plan -out=bootstrap.tfplan
AWS_PROFILE=stayhub terraform -chdir=infra/bootstrap apply bootstrap.tfplan
```

Creates the private versioned/encrypted state bucket with TLS enforcement. Bootstrap state stays local and ignored: retain a secure backup. Never delete that bucket during app teardown. Runtime uses S3 native locking, no DynamoDB. Commit `.terraform.lock.hcl`, never state, saved plans or private variable files.

## 2. Runtime infrastructure (user runs)

Create ignored `infra/runtime/terraform.tfvars` containing your real email:

```hcl
certificate_email = "you@example.com"
```

```sh
AWS_PROFILE=stayhub terraform -chdir=infra/runtime init
AWS_PROFILE=stayhub terraform -chdir=infra/runtime validate
AWS_PROFILE=stayhub terraform -chdir=infra/runtime plan -out=runtime.tfplan
AWS_PROFILE=stayhub terraform -chdir=infra/runtime apply runtime.tfplan
```

Review changes/cost before apply. OIDC is initially absent in the inspected sandbox; if someone creates the provider before apply, import it. IAM simulation allowed creation/pass-role, but SCPs/boundaries/service constraints may still reject apply. Do not broaden permissions to bypass account-owner restrictions. AMI uses the official AL2023 SSM parameter. Validate RDS 18 availability/class support in the user-generated plan/apply; version is configurable. EC2 bootstrap installs pinned Compose and Certbot; bootstrap failure must be resolved before deploy. EC2 user-data changes replace the instance; RDS/photo storage remain separate.

## 3. Initialize application secret and host config (user runs)

After apply and SSM agent online:

```sh
python3 infra/deploy/init-secrets.py
python3 infra/deploy/upload-config.py
AWS_PROFILE=stayhub terraform -chdir=infra/runtime output github_variables
```

The first script generates JWT_SECRET only if absent and sends it to Secrets Manager, not arguments/logs/state. It creates no seeded accounts. The second sends nonsecret connection/config identifiers to the instance through SSM. It waits for cloud-init; rerun after host replacement. Neither helper prints secrets. Runtime writes root-only `/opt/stayhub/runtime.env`. Demo seeding is a separate explicit operation requiring separately supplied SEED_* values in the application secret; never seed automatically on deploy.

Testing compromise: this initial stack uses the RDS-managed database administrator credentials for migrations and runtime. No database is public, but this is not a least-privilege production DB user. Split migrator/runtime DB users before real-user production. Automatic RDS credential rotation is disabled explicitly to prevent stale container passwords; rotate deliberately and redeploy to refresh credentials. Secrets Manager stores the password without placing it in Terraform state. DATABASE_URL requires TLS (`sslmode=require`); full CA hostname verification remains a production-hardening task.

## 4. GitHub variables and first deployment

Repository Settings → Secrets and variables → Actions → Variables: add the four values from `github_variables`: AWS_ROLE_ARN, EC2_INSTANCE_ID, RELEASE_BUCKET, DEPLOY_DOCUMENT. These identifiers are not secrets. Do not add AWS access keys. Workflow does not specify a GitHub environment, matching main-branch trust. Protect main; its code has permission to execute root deployment commands on the one instance and access release artifacts.

Commit source/lockfiles, push main. Workflow checks frontend lint/types/tests/build and backend lint/types/Postgres+isolated S3 tests, builds x86 backend, pushes SHA tag to ECR, packages React and deployment files to S3, then calls the single SSM deployment document. The host receiver locks before artifact download/staging, verifies the SHA256 and licensed assets, then starts the release script. The script loads secrets, pulls the exact image, runs Alembic, starts API/worker, obtains a certificate, updates Nginx/frontend and verifies real public HTTPS API responses. Certificates require public port80 challenge access; no app API runs on port80. First deploy may briefly show503 on HTTP while preparing TLS. The production API has no TCP listener.

ECR tags are immutable; workflow retries reuse the existing commit-tagged image after an explicit lookup rather than overwriting it. Inspect any timed-out SSM command before retrying; the host deployment lock rejects simultaneous updates. No force-push/tag replacement or automatic image pruning. Releases remain for rollback; manage accumulated ECR/S3/EBS usage deliberately.

Let’s Encrypt IP certs are short-lived (160h), using Certbot5.8 webroot and stable cert-name `stayhub`. A twice-daily systemd renewal timer reloads Nginx after renewal. Port80 serves the challenge and redirects other requests. Test renewal after deployment with `certbot renew --dry-run`; inspect timer failures/expiry. TLS issuance/renewal is not verified by Terraform validation. No domain purchase needed. Nginx/API use one origin, preserving current SameSite auth/CSRF behavior. Photos use signed cross-origin S3 URLs with bucket CORS for the exact public IP.

Failed release attempts restore previous application containers/frontend/Nginx when available. Database migrations are never reversed automatically and must be backward compatible. First release has no previous version. Brief deployment downtime is accepted for testing. Readiness currently checks DB/schema-table availability; migration success is separately enforced. Retain logs locally with bounded Docker rotation; remote log shipping/alerting is not implemented.

## Cost target and lifecycle

Budget: $40/month testing target, **not a guaranteed maximum**. Pricing estimate must include EC2 t3.small hours, 20GiB EBS, public IPv4, single-AZ db.t4g.micro hours and20GiB RDS storage, two secrets, S3/ECR storage, requests, data transfer and taxes. No credits/free tier assumed; no NAT/ALB charges. CPU credits use standard mode for EC2 to avoid unlimited CPU surcharges; RDS burst credits can still add cost. Use AWS Pricing Calculator for us-east-1 and an account-owner-approved budget alert before apply. Stop unused compute; RDS stopped instances automatically restart after7days, and disks/IP/snapshots continue charging. AWS Budgets is not a hard cap.

Deletion protection defaults true. To intentionally tear down: review backups, set deletion_protection=false and apply, then review destroy plan. RDS requires a final snapshot, and populated buckets/ECR refuse deletion. Existing `${name}-final` snapshot identifiers may conflict on repeated teardown; choose a new identifier in source when needed. Never force-delete data to make destroy pass. State bucket survives runtime teardown. Release files/secrets/certificates on the instance are reconstructed; photos/database are separate persistent resources.

## Verification status

Source preparation only. Local format/schema/shell/Python checks are recorded by the agent separately. No remote plan/apply, live certificate, RDS migration, browser auth/photo flow, worker or rollback verification is claimed until user-run deployment. Do not treat successful Terraform apply as application acceptance.

## Deployment-readiness corrections (master review)

Release delivery now uses a deterministic allowlisted archive containing React, deployment scripts, and `demo/assets/manifest.json` plus all five licensed images. License/source/creator/attribution metadata stays with the images. Packaging and receipt verify manifest sizes and SHA256 values. The workflow uploads to `releases/COMMIT_SHA/ARCHIVE_SHA256.tar.gz` and passes both identities to SSM. The checksum is an integrity binding to the selected workflow artifact, not an independent signature or publisher identity; OIDC/IAM protect publication.

A host-installed `/opt/stayhub/receive.py` (installed by Terraform user data) takes the deployment lock before any download, extraction, or release-directory creation. It downloads into a fresh staging directory, checks the digest, rejects traversal/links/special/duplicate members and oversized archives, verifies licensed assets, and promotes by rename. All deployment/recovery runs retain this same lock. Existing release IDs are never extracted over: an active identical retry only verifies the public API, a conflicting digest is rejected, and an existing non-active release requires a new commit rather than rewriting a previous/failed directory. No automatic data/release deletion is used. Changing this bootstrap replaces the EC2 instance on a future user-approved Terraform apply; database/photos remain separate.

Production Uvicorn listens **only on `/run/stayhub/api.sock`**, with no TCP8000 listener or published API port. Only the API container receives the socket mount. Nginx replaces forwarding headers with its connection's client address and fixed HTTPS scheme, strips `Forwarded`, and sends requests through the Unix socket. Uvicorn trusts proxy headers on this socket-only listener; the socket directory is root/nginx-only (0750); privileged host/container access remains trusted. Never add a TCP listener/port to this production configuration while trusting all socket forwarding headers. Local Dockerfile/Compose still disable proxy handling, so local auth behavior is unchanged. Nginx has no `real_ip_header` or untrusted incoming-header trust. SSM/IAM/root access is administrative, not an untrusted public client.

Release success requires both certificate-verified `https://ELASTIC_IP/api/ready` returning JSON `{"status":"ready"}` and `https://ELASTIC_IP/api/v1/auth/me` returning401 with the expected JSON authentication error. SPA HTML, redirects to the SPA, wrong status/schema, TLS errors or a broken proxy path fail the release. The readiness route is an Nginx mapping to backend `/ready`, not a frontend fallback. Recovery restores the previous image, frontend link and saved Nginx configuration, then repeats the public HTTPS API probes. Recovery failures are reported, never hidden with a success exit. First-release failure stops the attempted containers and restores the original proxy configuration. Migrations remain applied; backward-compatible schema changes are still required.

### Exact deployment commands (operator runs, not performed during review)

For an already provisioned stack with initialized secrets/config and repository variables:

```sh
# Publish/release a main-branch commit through the checked workflow:
gh workflow run deploy.yml --repo jigar225/stayhub --ref main
```

The workflow ID/file must already be committed on main. For a manual artifact delivery from a reviewed main checkout after checks pass and its image is in ECR:

```sh
npm --prefix frontend run build
release=$(git rev-parse HEAD)
digest=$(python3 infra/deploy/package.py --frontend frontend/dist --output /tmp/stayhub-release.tar.gz)
# Obtain these nonsecret values from terraform output github_variables:
bucket=jigar-stayhub-sandbox-762079300828-releases
instance_id=REPLACE_WITH_EC2_INSTANCE_ID
AWS_PROFILE=stayhub aws s3 cp /tmp/stayhub-release.tar.gz "s3://$bucket/releases/$release/$digest.tar.gz" --region us-east-1
AWS_PROFILE=stayhub aws ssm send-command --region us-east-1 --instance-ids "$instance_id" --document-name jigar-stayhub-sandbox-deploy --parameters "Release=$release,Sha256=$digest"
```

Inspect/wait for that SSM command's success; the send-command response alone does not mean deployed. No release script should be invoked directly outside the locked receiver. Active-identical retries probe without altering files; failed or previous IDs are immutable and need a new commit to redeploy. A manually invoked workflow rebuild can have a different frontend artifact digest for an existing commit; receipt intentionally rejects that conflict instead of replacing active files. Keep the original archive/digest for an exact retry.

### Exact explicit remote seed commands

After a successful ordinary deployment and initial JWT secret setup, from the project root:

```sh
aws sso login --profile stayhub
# Prompts privately for missing SEED_{GUEST,HOST,ADMIN}_{NAME,EMAIL,PASSWORD};
# keeps JWT and existing fields unchanged. Use distinct emails and 12–128-char passwords.
python3 infra/deploy/configure-demo-secrets.py
# Explicitly provisions accounts/policies and imports licensed listing content:
python3 infra/deploy/remote-seed.py
# Safe repeat: completed imports and host edits are preserved, not reset.
python3 infra/deploy/remote-seed.py
```

`remote-seed.py` uses the operator's SSO permission to invoke `AWS-RunShellScript`; GitHub's deployment role is deliberately not authorized for that document. It executes `seed.sh` under the same host lock, refreshes secret values, validates all nine seed fields and licensed assets before provisioning, then runs `app.seed` and `app.seed_content` with the selected release's `demo/` mounted **read-only** at `/demo-content`. Normal deployment, bootstrap and workflow never call either seed. No startup seed or destructive reset. Existing account passwords are preserved; if supplied existing-account credentials no longer match, import fails rather than resetting them. An interrupted or concurrently edited incomplete import may require investigation; do not delete markers or host edits to force it through. Demo account creation/content imports are intentionally user-run data mutations and were not run against any existing database during this review.

### Reproducible local checks

```sh
terraform fmt -check -recursive infra
terraform -chdir=infra/runtime validate
bash -n infra/deploy/bootstrap.sh infra/deploy/release.sh
backend/.venv/bin/python infra/tests/test_deployment.py
backend/.venv/bin/python infra/tests/test_proxy.py
backend/.venv/bin/python infra/tests/run_application_checks.py
backend/.venv/bin/python infra/tests/test_storage_credentials.py
```

`test_deployment.py` uses a real loopback HTTPS server with an explicitly trusted temporary certificate; AWS/Docker/Nginx/systemd operations are stubs for release transitions. `test_proxy.py` uses real Nginx/Uvicorn containers and actual application rate-limit code. `run_application_checks.py` uses read-only source and disposable isolated Postgres/S3 containers. These two Docker tests expect a locally built `stayhub-api:latest` image with backend dependencies (`docker build -t stayhub-api backend` if absent). Test resources use unique names and are cleaned up; no development DB/bucket is selected. See `docs/deployment-readiness-evidence.md` for actual results and limits.

## Shared-account resource naming

New runtime resources use `jigar-stayhub-sandbox` names and `Owner=jigar` tags. ECR is `jigar-stayhub/backend`; the GitHub role is `jigar-stayhub-github-deploy`. Resource types without configurable names receive a prefixed Name tag where supported. The GitHub OIDC provider URL is an account-level identity and cannot be renamed; reuse/import an existing matching provider rather than creating a duplicate.

State storage now targets `jigar-stayhub-762079300828-us-east-1-state`. Before this change, the old bucket was checked with ListObjectVersions: no versions or delete markers existed. The user is deleting that empty old bucket. Finish deletion before the next bootstrap plan: otherwise `prevent_destroy` correctly blocks replacement. Keep bootstrap local state; refresh during plan discovers the deleted bucket. Apply the newly reviewed bootstrap plan, then run `terraform -chdir=infra/runtime init -reconfigure` against the new empty backend. No runtime state migration is needed for this verified empty setup. Never reuse old saved plans.

Local paths, AWS profile, database name, photo object prefixes and GitHub repository identity remain unchanged.

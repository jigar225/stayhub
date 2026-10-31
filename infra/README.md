# StayHub sandbox deployment

Target: account **762079300828**, **us-east-1**, CLI profile **stayhub**. This replaces the old-account infrastructure source by user request; it does not delete old AWS resources. Additive provisioning for the S3/CloudFront milestone is explicitly authorized; review saved plans before applying. Existing sandbox resources with matching names must be imported rather than overwritten/recreated in another state.

## Architecture

One Amazon Linux 2023 x86 EC2 (`t3.small`, 2 GiB) with encrypted 20 GiB gp3 disk and Elastic IP. Nginx serves React and proxies `/api/` to the Unix-socket-only FastAPI container. Worker uses the same backend image. No SSH ingress, ALB, NAT, local Postgres or RustFS in deployment. CloudFront now serves the frontend from private S3 and proxies API requests to a separate trusted HTTPS EC2 hostname. Single-AZ RDS PostgreSQL 18 (`db.t4g.micro`, 20 GiB) is private; only the EC2 security group can reach it. Private S3 stores photos and release artifacts. GitHub OIDC can deploy only main from `jigar225/stayhub` with the previously supplied immutable owner/repository IDs. Update this trust subject if the repository is moved or workflow uses a GitHub environment.

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

The first script generates JWT_SECRET only if absent and sends it to Secrets Manager, not arguments/logs/state. It creates no accounts. The second sends nonsecret connection/config identifiers to the instance through SSM. It waits for cloud-init; rerun after host replacement. Neither helper prints secrets. Runtime writes root-only `/opt/stayhub/runtime.env`. Demo accounts/content are a separate explicit operation (`remote-provision.py`) that generates its own credentials; never provision automatically on deploy.

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

## Historical verification status (before CDN milestone)

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
digest=$(python3 infra/deploy/package.py --output /tmp/stayhub-release.tar.gz)
# Obtain these nonsecret values from terraform output github_variables:
bucket=jigar-stayhub-sandbox-762079300828-releases
instance_id=REPLACE_WITH_EC2_INSTANCE_ID
AWS_PROFILE=stayhub aws s3 cp /tmp/stayhub-release.tar.gz "s3://$bucket/releases/$release/$digest.tar.gz" --region us-east-1
AWS_PROFILE=stayhub aws ssm send-command --region us-east-1 --instance-ids "$instance_id" --document-name jigar-stayhub-sandbox-deploy --parameters "Release=$release,Sha256=$digest"
```

Inspect/wait for that SSM command's success; the send-command response alone does not mean deployed. No release script should be invoked directly outside the locked receiver. Active-identical retries probe without altering files; failed or previous IDs are immutable and need a new commit to redeploy. A manually invoked workflow rebuild can have a different frontend artifact digest for an existing commit; receipt intentionally rejects that conflict instead of replacing active files. Keep the original archive/digest for an exact retry.

### Exact explicit remote provisioning command

After a successful ordinary deployment and initial JWT secret setup, from the project root:

```sh
aws sso login --profile stayhub
# Explicitly creates demo users/hosts/guests and published stays with photos:
python3 infra/deploy/remote-provision.py
# Safe repeat: completed content and host edits are preserved, not reset.
python3 infra/deploy/remote-provision.py
# Fetch the one-time generated credentials file (never printed to logs):
aws ssm send-command --instance-ids "$instance_id" --document-name AWS-RunShellScript \
  --parameters commands="cat /opt/stayhub/provisioned-credentials.txt"
```

`remote-provision.py` uses the operator's SSO permission to invoke `AWS-RunShellScript`; GitHub's deployment role is deliberately not authorized for that document. It executes `provision.sh` under the same host lock, refreshes runtime env, validates every licensed asset, then runs `app.provision_users` with the selected release's `demo/` mounted **read-only** at `/demo-content`. It reads `demo/provision.json` and creates an admin, hosts and guests; each host's stays are published with real stored photos through the normal listing services, inside real per-host sessions. Normal deployment, bootstrap and workflow never call it; no startup provisioning or destructive reset. Reruns are idempotent: existing credentials and content (including host edits/unlisting) are preserved via stable UUIDs and demo markers. Generated account passwords are written only to `/opt/stayhub/provisioned-credentials.txt` (mode `0600`) and never to stdout/logs.

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


## S3/CloudFront frontend milestone

The public frontend uses the default CloudFront HTTPS domain and a private,
versioned, encrypted S3 bucket. OAC permits reads only from this distribution;
public access is blocked and plaintext S3 requests are denied. `/api` and
`/api/*` use the existing EC2 Unix-socket API through verified origin HTTPS.
The origin hostname is derived from the Terraform EIP:
`jigar-stayhub-api.<hyphenated-IP>.sslip.io`. No EC2 user-data changes are
required. The IP website, IP certificate, worker, RDS and photo/release buckets
remain in place. No new compute, Lambda, load balancer or purchased domain.

CloudFront uses `Managed-CachingDisabled` for the API and
`Managed-AllViewerExceptHostHeader` to retain Authorization, cookies, Origin,
CSRF/idempotency headers and query strings while using origin Host/SNI.
Error caching minimum TTL is zero; no error status/body is rewritten.
The frontend cache policy has minimum/default TTL zero and respects immutable
asset headers. The viewer-request function rewrites only known app navigation
routes. Missing assets, unknown paths and API paths are never converted into
`index.html`; S3 may return 403 for missing objects because public ListBucket
is intentionally unavailable.

`configure-origin.py` adds a separate API-only Nginx vhost and certificate,
with ACME on port 80 and HTTPS redirects elsewhere. Its include stays last so
the existing IP host remains the default for non-SNI connections. Certbot's
existing twice-daily timer renews both certificates and reloads Nginx. The
script is safe to repeat under `/opt/stayhub/deploy.lock`. It refreshes trusted
CloudFront origin-facing ranges from the official AWS IP range feed, and
installs a daily locked refresh timer. Only those connection peers may supply
CloudFront's appended (rightmost) XFF viewer address; other public clients'
forwarding headers are overwritten. Failed range download leaves the prior
configuration intact. Monitor both timers; a stale list can group requests
under an edge address and reduce rate-limit availability.

`release_config` now contains the exact CDN origin. `upload-config.py` sends
it to the host; `runtime-env.py` retains the IP origin, adds the CDN origin,
and keeps Secure cookies. Photo CORS likewise retains the IP origin and adds
only the exact CDN origin. API requests remain relative `/api/v1/...`.
The hostname itself is deliberately not added as a trusted browser origin.

### Deployment and frontend rollback

The workflow retains all existing checks, backend health probes and recovery.
Only after the SSM backend deployment reports success does it publish the
frontend with `publish-frontend.py`. Hashed assets upload before index promotion,
receive one-year immutable caching and are never deleted automatically.
`index.html` must revalidate. Each publish stores a snapshot plus SHA256 manifest
under `releases/COMMIT/INDEX_SHA256/`, then invalidates and waits for CloudFront.
A failed invalidation can leave a promoted release temporarily stale; inspect
its status and retry invalidation or restore a snapshot. Do not rerun backend
migrations merely to retry frontend publication.

Configure all six repository variables from `terraform output -json
github_variables`: the four existing values plus `FRONTEND_BUCKET` and
`CLOUDFRONT_DISTRIBUTION_ID`. OIDC trust is unchanged. IAM additions are limited
to GetObject/PutObject on the frontend bucket and invalidation creation/status
on the one distribution. No asset deletion or broad CloudFront access.

To roll back frontend content, use a snapshot URL from successful publish output
or the recorded milestone evidence, and the bucket/distribution Terraform outputs:

```sh
AWS_PROFILE=stayhub python3 infra/deploy/publish-frontend.py \
  --rollback-snapshot s3://BUCKET/releases/COMMIT/INDEX_SHA256/ \
  --bucket BUCKET --distribution DISTRIBUTION_ID
```

This downloads and verifies every file in the snapshot before publication,
uploads assets first, promotes the old index and waits for invalidation.
It does not roll back backend code or reverse migrations. Select a frontend
compatible with the running backend. S3 versioning is an additional recovery
layer. Keep previous assets/snapshots until a deliberate retention review.
The old IP URL remains available as a separate access path.

The free sslip.io hostname is an external DNS dependency, not an owned domain.
Availability, DNS/CAA changes and CA rate limits can interrupt issuance/renewal;
there is no insecure HTTP or certificate-verification bypass. If the EIP changes,
verify DNS and issue a certificate for the new hostname before applying dependent
origin changes. Monitor certificate expiry and both systemd timers. Official
references: [CloudFront origin headers](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/using-managed-origin-request-policies.html),
[error caching](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/custom-error-pages-expiration.html),
[client IP handling](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/RequestAndResponseBehaviorCustomOrigin.html),
[Terraform distribution resource](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudfront_distribution),
and [Certbot webroot/renewal](https://eff-certbot.readthedocs.io/en/stable/using.html).

Current applied resources, checks and limitations are recorded in
`infra/CDN-MILESTONE.md`. A local infrastructure apply does not establish that
the changed GitHub workflow ran: that run remains pending the user's commit/push.


## Backend-only archives: pending reviewed cleanup

This section supersedes earlier descriptions of bundling React into EC2 releases.
The prepared flow is checks/build → immutable backend image → backend-only SSM
release → API health → S3 frontend publication. Frontend publication still uploads
assets before index and retains previous hashed assets. The explicit post-backend
probe uses the current CDN URL in the workflow; update that URL if the distribution
is intentionally replaced. No workflow has been dispatched or live host updated
for this cleanup. Stop for review before commit/push.

New EC2 archives contain `release.json` (`stayhub-backend`, version 2), deployment
files and required licensed demo assets, with no `frontend/` tree. Receiver v2
accepts this format and validates legacy unversioned archives with
`frontend/index.html`. The digest, safe member extraction, licensed-asset checks,
lock-before-download and immutable-release retry behavior remain. Active identical
legacy retries still probe without extracting or changing files; inactive existing
release IDs still require a new commit. Keeping legacy validation does not authorize
redeploying an old script that publishes frontend content onto EC2.

The new backend release script no longer reads/writes/promotes `/var/www/stayhub`
or depends on that tree during recovery. It retains the TLS IP/API proxy, the
separate HTTPS origin include, certificate handling and backend health/recovery.
After a future successful backend deployment, non-API IP routes return 404 rather
than serving React. No IP-to-CDN redirect is part of this narrowed cleanup. Existing
web archives and symlinks remain on disk. Migrations retain their existing behavior
and are never reversed by backend recovery. The actual post-push GitHub run remains
pending; the live site has not been changed by this cleanup.

### Required operator step BEFORE the first backend-only deployment

The currently installed receiver expects `frontend/index.html`. Run the following
from the reviewed checkout **before pushing/dispatching a backend-only release**.
These commands only replace `/opt/stayhub/receive.py` under the existing deployment
lock, after checking the source checksum and Python syntax. They do not run a
release, restart services, migrate data or modify immutable release directories.
A same-checksum repeat is a no-op. This is an operator procedure, not a new
migration service or backup system. No SSM command below was executed by the agent.

1. Prepare SSM parameters locally from the reviewed receiver:

```sh
cd /Users/macair/Stayhub
python3 - <<'PY_RECEIVER'
import base64
import hashlib
import json
from pathlib import Path

source = Path("infra/deploy/receive.py").read_bytes()
compile(source, "receive.py", "exec")
digest = hashlib.sha256(source).hexdigest()
encoded = base64.b64encode(source).decode("ascii")
script = """import base64, fcntl, hashlib, os, tempfile
from pathlib import Path
root = Path('/opt/stayhub')
source = base64.b64decode('ENCODED', validate=True)
expected = 'DIGEST'
assert hashlib.sha256(source).hexdigest() == expected
compile(source, 'receive.py', 'exec')
with (root / 'deploy.lock').open('a') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    target = root / 'receive.py'
    if hashlib.sha256(target.read_bytes()).hexdigest() == expected:
        print('Receiver already current:', expected)
    else:
        fd, candidate = tempfile.mkstemp(prefix='.receive-', suffix='.py', dir=root)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(source)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), 0o700)
        os.replace(candidate, target)
        assert hashlib.sha256(target.read_bytes()).hexdigest() == expected
        print('Receiver updated:', expected)
""".replace("ENCODED", encoded).replace("DIGEST", digest)
parameters = {"commands": ["set -eu\npython3 - <<'PY_REMOTE'\n" + script + "PY_REMOTE\n"]}
Path("/tmp/stayhub-receiver-parameters.json").write_text(json.dumps(parameters))
print("Expected receiver SHA256:", digest)
PY_RECEIVER
```

2. Verify the account, send that exact update, and inspect completion:

```sh
set -euo pipefail
test "$(aws sts get-caller-identity --profile stayhub --region us-east-1 --query Account --output text)" = 762079300828
command_id=$(aws ssm send-command \
  --profile stayhub --region us-east-1 \
  --instance-ids i-06cf083f7d5bd377d \
  --document-name AWS-RunShellScript \
  --parameters file:///tmp/stayhub-receiver-parameters.json \
  --query Command.CommandId --output text)
printf 'Receiver update command: %s\n' "$command_id"
aws ssm wait command-executed \
  --profile stayhub --region us-east-1 \
  --command-id "$command_id" --instance-id i-06cf083f7d5bd377d
aws ssm get-command-invocation \
  --profile stayhub --region us-east-1 \
  --command-id "$command_id" --instance-id i-06cf083f7d5bd377d \
  --query '{Status:Status,Code:ResponseCode,Output:StandardOutputContent,Error:StandardErrorContent}'
```

Require `Status=Success`, `Code=0`, and the expected SHA256 in output. If waiting
fails or times out, inspect that command with `get-command-invocation` before any
retry or deployment. An active deployment causes the nonblocking lock to reject
the update; wait for it to finish, then repeat this same procedure. Do not delete
the lock or run the receiver update concurrently with a deployment. Failed
pre-replacement checks leave the installed receiver intact. No old web/release
files need deletion. Terraform/user-data changes are outside this cleanup; any
pre-existing Terraform modifications require separate review, not an apply here.

3. After reviewing the code and confirming the receiver update, selectively
commit/push the intended files and inspect the first real workflow run. Do not
include the unrelated M7 changes without their own review. A failed backend or
API-health step prevents the S3 publisher from running; do not rerun backend
migrations solely to retry a frontend publication. Existing frontend snapshot
rollback instructions above remain unchanged.

Files changed for this narrow cleanup: `.github/workflows/deploy.yml`,
`infra/deploy/package.py`, `infra/deploy/receive.py`, `infra/deploy/release.sh`,
`infra/tests/test_deployment.py`, and this README. Pre-existing changes in other
infrastructure and M7 files were retained, not modified by this cleanup.


### Focused cleanup verification results

All final commands below exited 0:

```sh
backend/.venv/bin/python infra/tests/test_deployment.py
# 17 tests: backend-only contents, legacy validation, invalid format,
# safe extraction, digest rejection, locking/retries, TLS probes, recovery,
# and no new or modified EC2 frontend copy/symlink.
backend/.venv/bin/python infra/tests/test_frontend_delivery.py
# 5 existing frontend-publication/routing checks.
backend/.venv/bin/ruff check --config backend/pyproject.toml infra/deploy/package.py infra/deploy/receive.py infra/tests/test_deployment.py
bash -n infra/deploy/release.sh
python3 -m py_compile infra/deploy/package.py infra/deploy/receive.py infra/tests/test_deployment.py
/tmp/stayhub-check-tools/actionlint -shellcheck= -pyflakes= .github/workflows/deploy.yml
git diff --check
```

Workflow YAML parsing, all workflow shell steps (`bash -n`), explicit
backend → API health → frontend ordering and failure gating were also checked
locally. Actionlint v1.7.12 ran with optional external ShellCheck/Pyflakes
integration disabled; Python and shell syntax checks ran separately. The manual
SSM preparation block was executed locally, and its remote Python was checked
for Python 3.9 syntax and tested only against temporary files for lock exclusion,
checksum installation and no-op repeat behavior. No SSM or live update ran.

The initial sandbox test attempt could not bind the loopback TLS server. The
final isolated test run used authorized local socket access. One new macOS path
assertion was corrected to compare resolved paths; the final 17-test suite
passed. The unchanged application/M7 files matched their recorded hashes.
Nothing was committed, pushed, dispatched or deployed. Actual GitHub execution
and the installed-receiver update remain pending operator action.

### Optional server-only address autocomplete

Geoapify autocomplete is optional. Hosts can enter an address and manually
confirm a map pin without a provider key. Set `GEOAPIFY_API_KEY` only in the
backend environment/application secret. Never use `VITE_*`, frontend build
arguments, command-line key values, source files, logs, or chat to supply it.

For local development, privately fill `GEOAPIFY_API_KEY` in the ignored `.env`
(or the selected isolated review env file). `GEOAPIFY_DAILY_BUDGET` defaults to
2800 attempted provider calls per UTC day and accepts 1–3000. Failed calls count;
the same key's use outside this installation needs its own quota headroom.

For a future authorized deployment, an operator can run
`python3 infra/deploy/configure-geoapify-secret.py` from the repository root.
It uses the existing `stayhub` AWS profile and Terraform `release_config`, reads
the initialized application secret, prompts for the key privately, and preserves
JWT and other fields. A blank key leaves the secret unchanged.
The optional budget is also prompted; AWS input uses a mode-0600 temporary file
and captured diagnostics. This command updates a secret only: it does not deploy,
restart services or provision data. Do not run it as part of source-only review.

`infra/deploy/runtime-env.py` allowlists these two application-secret fields into
the root-only backend `runtime.env`; absent key becomes empty and absent budget
becomes 2800. Existing deployment then consumes that file for API/worker only.
After an explicitly authorized release/restart, verify autocomplete once using a
host's explicit typed search. Unit/browser suites must keep using a mocked
provider boundary and do not count as live-provider acceptance. Missing private
credentials block only that live check. The map uses OpenFreeMap independently;
public listing locations remain approximate and owner coordinates remain private.

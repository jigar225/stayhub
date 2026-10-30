import { useRef, useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import {
  ApiError,
  login,
  register,
  safeReturnPath,
  RegisteredLoginError,
} from "../api/client";
import { Button, ErrorState } from "../components/ui";
export function AuthPage({ signup = false }: { signup?: boolean }) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const formRef = useRef<HTMLFormElement>(null);
  type FieldName = "name" | "email" | "password";
  const [fieldErrors, setFieldErrors] = useState<
    Partial<Record<FieldName, string>>
  >({});
  function showFields(fields: Partial<Record<FieldName, string>>) {
    setFieldErrors(fields);
    const first = (["name", "email", "password"] as const).find(
      (field) => fields[field],
    );
    if (first)
      (
        formRef.current?.elements.namedItem(first) as HTMLInputElement | null
      )?.focus();
  }
  const [registered, setRegistered] = useState(false);
  const navigate = useNavigate();
  const [params] = useSearchParams();
  async function submit(e: FormEvent) {
    e.preventDefault();
    const form = formRef.current!;
    const fields: Partial<Record<FieldName, string>> = {};
    if (signup && (!name.trim() || name.trim().length > 100))
      fields.name = "Enter your name (1–100 characters, not only spaces).";
    const emailInput = form.elements.namedItem("email") as HTMLInputElement;
    if (
      !email.trim() ||
      emailInput.validity.typeMismatch ||
      email.trim().length > 254
    )
      fields.email = "Enter a valid email address (up to 254 characters).";
    const minimum = signup ? 12 : 1;
    if (
      Array.from(password).length < minimum ||
      Array.from(password).length > 128
    )
      fields.password = `Use ${minimum}–128 characters for your password.`;
    setError("");
    showFields(fields);
    if (Object.keys(fields).length) return;
    setBusy(true);
    setError("");
    try {
      if (signup && !registered) {
        try {
          await register(name.trim(), email.trim().toLowerCase(), password);
        } catch (error) {
          if (error instanceof RegisteredLoginError) setRegistered(true);
          throw error;
        }
      } else await login(email.trim().toLowerCase(), password);
      navigate(safeReturnPath(params.get("returnTo")), { replace: true });
    } catch (e) {
      const fields: Partial<Record<FieldName, string>> = {};
      if (e instanceof ApiError && e.details.field_errors) {
        for (const field of ["name", "email", "password"] as const) {
          const message = e.details.field_errors[field];
          if (message && (field !== "name" || signup))
            fields[field] = Array.isArray(message)
              ? message.join(" ")
              : message;
        }
      }
      showFields(fields);
      if (!Object.keys(fields).length)
        setError(e instanceof Error ? e.message : "Please try again.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="auth-layout">
      <div className="auth-intro">
        <span className="eyebrow">WELCOME TO STAYHUB</span>
        <h1>{signup ? "Make yourself at home." : "Welcome back."}</h1>
        <p>
          {signup
            ? "One account for your travels, and a place to begin hosting."
            : "Log in to manage your profile and switch between traveling and hosting."}
        </p>
        <div className="auth-note">
          <span className="brand-mark" aria-hidden="true">
            ⌂
          </span>
          <p>
            A simpler place to stay.
            <br />
            <span className="muted">Your next chapter starts here.</span>
          </p>
        </div>
      </div>
      <section className="auth-card" aria-labelledby="auth-heading">
        <h2 id="auth-heading">
          {signup ? "Create your account" : "Log in to StayHub"}
        </h2>
        <p className="muted">
          {signup
            ? "Join as a guest. Start hosting when you’re ready."
            : "Enter your email and password to continue."}
        </p>
        <form ref={formRef} noValidate onSubmit={(e) => void submit(e)}>
          {signup && (
            <label>
              <span id="name-label">Full name</span>
              <input
                autoComplete="name"
                name="name"
                aria-labelledby="name-label"
                aria-invalid={!!fieldErrors.name}
                aria-describedby={
                  [fieldErrors.name ? "name-error" : "", ""]
                    .filter(Boolean)
                    .join(" ") || undefined
                }
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                maxLength={100}
              />
              {fieldErrors.name && (
                <span className="field-error" id="name-error">
                  {fieldErrors.name}
                </span>
              )}
            </label>
          )}
          <label>
            <span id="email-label">Email address</span>
            <input
              name="email"
              aria-labelledby="email-label"
              aria-invalid={!!fieldErrors.email}
              aria-describedby={
                [fieldErrors.email ? "email-error" : "", ""]
                  .filter(Boolean)
                  .join(" ") || undefined
              }
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              maxLength={254}
            />
            {fieldErrors.email && (
              <span className="field-error" id="email-error">
                {fieldErrors.email}
              </span>
            )}
          </label>
          <label>
            <span id="password-label">Password</span>
            <input
              name="password"
              aria-labelledby="password-label"
              aria-invalid={!!fieldErrors.password}
              aria-describedby={
                [
                  fieldErrors.password ? "password-error" : "",
                  signup ? "password-help" : "",
                ]
                  .filter(Boolean)
                  .join(" ") || undefined
              }
              type="password"
              autoComplete={signup ? "new-password" : "current-password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={signup ? 12 : 1}
              maxLength={128}
            />
            {fieldErrors.password && (
              <span className="field-error" id="password-error">
                {fieldErrors.password}
              </span>
            )}
          </label>
          {signup && (
            <p className="field-help" id="password-help">
              Use 12–128 characters.
            </p>
          )}
          {error && <ErrorState message={error} />}
          <Button type="submit" disabled={busy}>
            {busy
              ? "Please wait…"
              : registered
                ? "Log in"
                : signup
                  ? "Create account"
                  : "Log in"}
          </Button>
        </form>
        <p className="auth-switch">
          {signup ? "Already have an account?" : "New to StayHub?"}{" "}
          <Link
            to={`${signup ? "/login" : "/signup"}${params.get("returnTo") ? `?returnTo=${encodeURIComponent(safeReturnPath(params.get("returnTo")))}` : ""}`}
          >
            {signup ? "Log in" : "Sign up"}
          </Link>
        </p>
      </section>
    </main>
  );
}

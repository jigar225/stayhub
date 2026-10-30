import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, expect, it, vi } from "vitest";
import { AuthPage } from "../src/pages/AuthPage";
const { login, register } = vi.hoisted(() => ({
  login: vi.fn(),
  register: vi.fn(),
}));
vi.mock("../src/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../src/api/client")>()),
  login,
  register,
}));
beforeEach(() => {
  login.mockReset();
  register.mockReset();
});
it("shows login failure and preserves inputs for recovery", async () => {
  login.mockRejectedValue(new Error("Invalid email or password"));
  render(
    <MemoryRouter>
      <AuthPage />
    </MemoryRouter>,
  );
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Email address"), "guest@example.com");
  await user.type(screen.getByLabelText("Password"), "incorrect-password");
  await user.click(screen.getByRole("button", { name: "Log in" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Invalid email or password",
  );
  expect(screen.getByLabelText("Email address")).toHaveValue(
    "guest@example.com",
  );
  expect(screen.getByRole("button", { name: "Log in" })).toBeEnabled();
});

it("renders backend field errors, focuses first field and preserves values", async () => {
  const { ApiError } = await import("../src/api/client");
  register.mockRejectedValue(
    new ApiError(422, {
      code: "validation_error",
      message: "Check the highlighted fields.",
      field_errors: {
        email: "Enter a valid email address.",
        password: ["Use 12–128 characters for your password."],
      },
      request_id: "test",
    }),
  );
  render(
    <MemoryRouter>
      <AuthPage signup />
    </MemoryRouter>,
  );
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Full name"), " Guest ");
  await user.type(screen.getByLabelText("Email address"), "GUEST@example.com");
  await user.type(screen.getByLabelText("Password"), " password-with-spaces ");
  await user.click(screen.getByRole("button", { name: "Create account" }));
  expect(await screen.findByText("Enter a valid email address.")).toBeVisible();
  expect(screen.getByLabelText("Email address")).toHaveFocus();
  expect(screen.getByLabelText("Email address")).toHaveAttribute(
    "aria-invalid",
    "true",
  );
  expect(screen.getByLabelText("Password")).toHaveAccessibleDescription(
    /Use 12–128/,
  );
  expect(screen.getByLabelText("Password")).toHaveValue(
    " password-with-spaces ",
  );
  expect(register).toHaveBeenCalledWith(
    "Guest",
    "guest@example.com",
    " password-with-spaces ",
  );
});

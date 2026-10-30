// M1 transport types conform to docs/api-contract.md and backend OpenAPI.
export type Role = "guest" | "host" | "admin";
export interface User {
  id: string;
  name: string;
  email: string;
  roles: Role[];
}
export interface AuthResponse {
  user: User;
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  csrf_token: string;
}
export interface ErrorEnvelope {
  error: {
    code: string;
    message: string;
    field_errors: Record<string, string | string[]> | null;
    request_id: string;
  };
}

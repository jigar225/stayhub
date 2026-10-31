import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, expect, it, vi } from "vitest";
import { ReviewForm } from "../src/reviews/ReviewForm";
import { ListingReviews } from "../src/reviews/ListingReviews";
import type { PartyReviews, Review } from "../src/reviews/api";
const api = vi.hoisted(() => ({
  party: vi.fn(),
  submit: vi.fn(),
  listing: vi.fn(),
}));
const actor = vi.hoisted(() => ({ id: "guest" }));
vi.mock("../src/reviews/api", async (original) => ({
  ...(await original<typeof import("../src/reviews/api")>()),
  reviewApi: api,
}));
vi.mock("../src/auth/useSession", () => ({
  useSession: () => ({ user: actor }),
}));
const own: Review = {
  id: "r",
  author_role: "guest",
  author_name: "Guest",
  text: "<script>private text</script>",
  overall: 4,
  categories: { cleanliness: 4 },
  submitted_at: "2027-01-02T00:00:00Z",
  published_at: null,
};
const open: PartyReviews = {
  reservation_id: "stay",
  listing_title: "Actual booked stay",
  role: "guest",
  eligible: true,
  deadline: "2027-01-16T00:00:00Z",
  own: null,
  counterpart: null,
  status: "open",
};
function form() {
  return render(
    <MemoryRouter initialEntries={["/trips/stay/review"]}>
      <Routes>
        <Route path="/trips/:id/review" element={<ReviewForm />} />
      </Routes>
    </MemoryRouter>,
  );
}
beforeEach(() => {
  vi.resetAllMocks();
  api.party.mockResolvedValue(open);
  api.submit.mockResolvedValue({
    ...open,
    eligible: false,
    own,
    status: "submitted",
  });
  api.listing.mockResolvedValue({
    items: [],
    count: 0,
    average: null,
    next_cursor: null,
  });
});
it("requires all guest ratings and immutability acknowledgement before submission", async () => {
  form();
  const submit = await screen.findByRole("button", { name: "Submit review" });
  expect(submit).toBeDisabled();
  expect(
    screen.getByText(/Your submitted review cannot be edited/),
  ).toBeVisible();
  for (const select of screen.getAllByRole("combobox"))
    fireEvent.change(select, { target: { value: "4" } });
  fireEvent.change(screen.getByLabelText("Public review"), {
    target: { value: "An honest review" },
  });
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(submit);
  await screen.findByText("Your submitted review");
  expect(api.submit).toHaveBeenCalledWith("stay", {
    text: "An honest review",
    overall: 4,
    categories: {
      cleanliness: 4,
      accuracy: 4,
      check_in: 4,
      communication: 4,
      location: 4,
      value: 4,
    },
  });
  expect(
    screen.queryByRole("button", { name: "Submit review" }),
  ).not.toBeInTheDocument();
  expect(screen.getByText(/Saved privately/)).toBeVisible();
  expect(document.querySelector("script")).toBeNull();
});
it("host review describes guest without listing ratings", async () => {
  api.party.mockResolvedValue({ ...open, role: "host" });
  form();
  await screen.findByLabelText("Review of your guest");
  expect(screen.queryAllByRole("combobox")).toHaveLength(0);
  fireEvent.change(screen.getByLabelText("Review of your guest"), {
    target: { value: "A considerate guest" },
  });
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Submit review" }));
  await waitFor(() =>
    expect(api.submit).toHaveBeenCalledWith("stay", {
      text: "A considerate guest",
    }),
  );
});
it("resolves dropped submission response from own saved review", async () => {
  api.party
    .mockResolvedValueOnce(open)
    .mockResolvedValue({ ...open, eligible: false, own, status: "submitted" });
  api.submit.mockRejectedValue(new Error("Dropped response"));
  form();
  await screen.findByLabelText("Public review");
  fireEvent.change(screen.getByLabelText("Public review"), {
    target: { value: "Written once" },
  });
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.submit(
    screen.getByRole("button", { name: "Submit review" }).closest("form")!,
  );
  await screen.findByText("Your submitted review");
  expect(api.submit).toHaveBeenCalledTimes(1);
  expect(screen.queryByText("Dropped response")).not.toBeInTheDocument();
});
it("public review errors retry without inventing ratings", async () => {
  api.listing.mockRejectedValueOnce(new Error("Temporary failure"));
  render(<ListingReviews listingId="listing" />);
  await screen.findByText("Temporary failure");
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  await screen.findByText("No published guest reviews yet.");
  expect(screen.queryByText(/5\.00/)).not.toBeInTheDocument();
});

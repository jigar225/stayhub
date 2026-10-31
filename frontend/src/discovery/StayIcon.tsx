export function StayIcon({ name }: { name: string }) {
  const paths: Record<string, string> = {
    "": "M3 10 12 3l9 7M5 9v12h5v-7h4v7h5V9",
    beachfront: "M2 9q3-3 6 0t6 0 6 0M2 14q3-3 6 0t6 0 6 0",
    "amazing-views": "m2 20 6-12 5 9 3-6 6 9ZM17 5a2 2 0 1 0 0-.01",
    cabins: "m12 2-5 8h3l-5 7h5v5h4v-5h5l-5-7h3Z",
    design: "M12 2v5m0 10v5M2 12h5m10 0h5",
    farms: "M20 3C9 3 4 8 4 20c11-1 16-7 16-17ZM4 20 16 7",
    "tiny-homes": "M3 21V8h18v13M3 16h18M6 8V5h5v3m2 0V5h5v3",
    pools:
      "M12 2v3m0 14v3M2 12h3m14 0h3M5 5l2 2m10 10 2 2M5 19l2-2M17 7l2-2M16 12a4 4 0 1 0-8 0 4 4 0 0 0 8 0",
    "off-grid": "m12 3-10 18h20ZM12 3v18M7 21l5-18 5 18",
    historic: "m2 8 10-5 10 5ZM4 11v8m5-8v8m6-8v8m5-8v8M2 22h20",
    calendar:
      "M7 3v4m10-4v4M3 10h18M5 5h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2Z",
    filters: "M4 7h16M7 12h10M10 17h4",
    search: "M16 10a6 6 0 1 0-12 0 6 6 0 0 0 12 0Zm-2 4 6 6",
  };
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={paths[name] ?? paths[""]} />
    </svg>
  );
}

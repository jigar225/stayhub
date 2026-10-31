export type Bounds = {
  west: number;
  south: number;
  east: number;
  north: number;
};
export function boundsQuery(bounds: Bounds) {
  return Object.fromEntries(
    (["west", "south", "east", "north"] as const).map((key) => [
      key,
      String(Number(bounds[key].toFixed(5))),
    ]),
  );
}
export function listingsQuery(params: URLSearchParams) {
  const query = new URLSearchParams(params);
  const map = query.get("view") === "map";
  query.delete("view");
  query.delete("move");
  if (map) {
    query.set("map", "true");
    query.set("limit", "50");
    query.delete("cursor");
  } else {
    query.delete("map");
    for (const key of ["west", "south", "east", "north"]) query.delete(key);
  }
  return query.toString();
}

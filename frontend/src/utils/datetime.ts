const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

const RESOLVED_DATETIME_PATTERN = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/;

/**
 * Formats a backend-resolved ISO 8601 datetime (e.g.
 * "2026-09-03T15:00:00+05:30") as "September 3, 2026 at 3:00 PM".
 *
 * Reads the literal date/time digits directly instead of going through a
 * JS `Date` - the backend already resolved the expression into the
 * application's configured timezone, so those digits ARE the intended
 * wall-clock time. Parsing via `Date` and formatting with `Intl` would
 * silently reinterpret it in the viewer's browser timezone instead.
 */
export function formatResolvedDatetime(resolvedDatetime: string): string {
  const match = RESOLVED_DATETIME_PATTERN.exec(resolvedDatetime);
  if (!match) {
    return resolvedDatetime;
  }

  const [, year, month, day, hour, minute] = match;
  const monthName = MONTH_NAMES[Number(month) - 1];
  if (!monthName) {
    return resolvedDatetime;
  }

  const hourNumber = Number(hour);
  const period = hourNumber >= 12 ? "PM" : "AM";
  const hour12 = hourNumber % 12 === 0 ? 12 : hourNumber % 12;

  return `${monthName} ${Number(day)}, ${year} at ${hour12}:${minute} ${period}`;
}

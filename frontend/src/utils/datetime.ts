const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

const RESOLVED_DATETIME_PATTERN = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/;
const RESOLVED_DATE_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;
const RESOLVED_TIME_PATTERN = /^(\d{2}):(\d{2})/;

function to12Hour(hour24: number): { hour12: number; period: "AM" | "PM" } {
  const period = hour24 >= 12 ? "PM" : "AM";
  const hour12 = hour24 % 12 === 0 ? 12 : hour24 % 12;
  return { hour12, period };
}

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

  const { hour12, period } = to12Hour(Number(hour));

  return `${monthName} ${Number(day)}, ${year} at ${hour12}:${minute} ${period}`;
}

/**
 * Formats a backend-resolved date-only value (e.g. "2026-09-11", no time
 * component - the corresponding time is still missing) as
 * "September 11, 2026". Same literal-digit approach as
 * `formatResolvedDatetime` - no timezone reinterpretation.
 */
export function formatResolvedDate(resolvedDate: string): string {
  const match = RESOLVED_DATE_PATTERN.exec(resolvedDate);
  if (!match) {
    return resolvedDate;
  }

  const [, year, month, day] = match;
  const monthName = MONTH_NAMES[Number(month) - 1];
  if (!monthName) {
    return resolvedDate;
  }

  return `${monthName} ${Number(day)}, ${year}`;
}

/**
 * Formats a backend-resolved time-only value (e.g. "15:00:00", the date is
 * still missing) as "03:00 PM" - zero-padded 12-hour clock with AM/PM, the
 * same convention the native `<input type="time">` picker uses.
 */
export function formatResolvedTime(resolvedTime: string): string {
  const match = RESOLVED_TIME_PATTERN.exec(resolvedTime);
  if (!match) {
    return resolvedTime;
  }

  const [, hour, minute] = match;
  const { hour12, period } = to12Hour(Number(hour));
  const paddedHour = String(hour12).padStart(2, "0");

  return `${paddedHour}:${minute} ${period}`;
}

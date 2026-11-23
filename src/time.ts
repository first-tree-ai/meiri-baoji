const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

export function localDate(date: Date, timezone: string): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  }).formatToParts(date);
  const value = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${value.year}-${value.month}-${value.day}`;
}

function parseDate(date: string): Date {
  if (!ISO_DATE.test(date)) throw new Error(`Invalid ISO date: ${date}`);
  return new Date(`${date}T00:00:00Z`);
}

export function addDays(date: string, days: number): string {
  const value = parseDate(date);
  value.setUTCDate(value.getUTCDate() + days);
  return value.toISOString().slice(0, 10);
}

export function cycleStart(date: string): string {
  const value = parseDate(date);
  const weekday = value.getUTCDay();
  const daysSinceMonday = (weekday + 6) % 7;
  return addDays(date, -daysSinceMonday);
}

export function nextCycleStart(date: string): string {
  return addDays(cycleStart(date), 7);
}

export function inCycle(date: string, start: string): boolean {
  return date >= start && date < addDays(start, 7);
}

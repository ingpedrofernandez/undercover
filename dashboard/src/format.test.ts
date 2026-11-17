import { expect, it } from "vitest";
import { addOnName, cost, date, duration, label, money } from "./format";

it("formats money in US dollars", () => {
  expect(money(1150)).toBe("$1,150.00");
  expect(money(0)).toBe("$0.00");
});

it("formats dates without shifting the day", () => {
  expect(date("2026-06-24")).toBe("Jun 24, 2026");
});

it("turns codes into labels", () => {
  expect(label("trip_delay")).toBe("Trip delay");
  expect(addOnName("electronics_plus")).toBe("Electronics Plus");
  expect(addOnName("new_add_on")).toBe("New add on");
});

it("formats model costs to a hundredth of a cent", () => {
  expect(cost(0.0042)).toBe("$0.0042");
  expect(cost(1.5)).toBe("$1.5000");
});

it("formats durations in minutes and seconds", () => {
  expect(duration(0)).toBe("0s");
  expect(duration(59.6)).toBe("1m 0s");
  expect(duration(192)).toBe("3m 12s");
});

import { describe, expect, it } from "vitest";
import { formatINR, humanise, inIndianUnits, money, signedMoney } from "./format";

describe("money formatting", () => {
  it("uses the rupee sign and Indian digit grouping", () => {
    expect(formatINR(1500000)).toBe("₹15,00,000");
    expect(formatINR(430500)).toBe("₹4,30,500");
    expect(formatINR(0)).toBe("₹0");
  });
  it("shows a missing value as missing, never as zero", () => {
    expect(money(null)).toBe("Not available");
    expect(money(undefined)).toBe("Not available");
    expect(money(0)).toBe("₹0");
  });
  it("signs a change so a saving and a cost cannot be confused", () => {
    expect(signedMoney(-16139)).toBe("−₹16,139");
    expect(signedMoney(333194)).toBe("+₹3,33,194");
    expect(signedMoney(0)).toBe("₹0");
  });
  it("reads amounts in lakh and crore", () => {
    expect(inIndianUnits(1500000)).toBe("15 lakh");
    expect(inIndianUnits(14000000)).toBe("1.4 crore");
    expect(inIndianUnits(49690)).toBe("49.69 thousand");
  });
  it("turns field names into labels", () => expect(humanise("avg_business_receipts")).toBe("Avg business receipts"));
});

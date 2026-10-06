import { cn } from "@/lib/utils";

describe("cn", () => {
  it("merges conflicting tailwind classes keeping the last", () => {
    expect(cn("px-2", "px-4")).toBe("px-4");
  });
});

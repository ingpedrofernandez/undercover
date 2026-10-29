import { expect, test } from "@playwright/test";

test("the queue lists every claim", async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Claims queue" }),
  ).toBeVisible();
  await expect(page.locator("tbody tr")).toHaveCount(25);
  const last = page.getByRole("row").filter({ hasText: "CLM-1025" });
  await expect(last.getByText("Waiting")).toBeVisible();
});

test("a claim opens from the queue", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "CLM-1001" }).click();
  await expect(page).toHaveURL("/claims/CLM-1001");
  await expect(page.getByText(/My flight home from Rome/)).toBeVisible();
  await expect(
    page.getByText("Hotel Aurelia Fiumicino", { exact: false }),
  ).toBeVisible();
  await expect(page.getByText("POL-2001")).toBeVisible();
});

test("the header opens the instructions", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Instructions" }).click();
  await expect(page).toHaveURL("/instructions");
  const part = (name: string) =>
    page.locator("section", { has: page.getByRole("heading", { name }) });
  await expect(
    part("Running the queue").getByText(/You run UnderCover Travel/),
  ).toBeVisible();
  await expect(
    part("Working a claim").getByText(/You decide one travel insurance/),
  ).toBeVisible();
  await expect(
    page.getByText("## 10. How we work out your payment"),
  ).toHaveCount(0);
  await expect(page.getByRole("textbox")).toHaveCount(0);
  await expect(page.getByRole("button")).toHaveCount(0);
});

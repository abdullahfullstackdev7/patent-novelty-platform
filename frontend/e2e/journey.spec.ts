import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { mockApi } from "./mockApi";

// Full user journey in a real browser: log in, create a case, run it, read the chart, override a cell,
// submit, approve and export. The backend is simulated in mockApi.ts so the run needs no database or models.

test("public website to approved report", async ({ page }) => {
  const state = await mockApi(page);

  // The public site's Log in link reaches the login page.
  await page.goto("/");
  await page.getByRole("banner").getByRole("link", { name: "Log in" }).click();
  await expect(page).toHaveURL(/\/login$/);

  // Wrong password, then the right one.
  await page.getByLabel("Email").fill("attorney@example.com");
  await page.getByLabel("Password").fill("wrong");
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.getByText("The email or password is incorrect.")).toBeVisible();
  await page.getByLabel("Password").fill("correct horse");
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.getByRole("heading", { name: "Welcome, Alex" })).toBeVisible();
  await expect(page.getByText("No cases yet")).toBeVisible();

  // The access token is never written to browser storage.
  const stored = await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }));
  expect(stored).not.toContain("tok");

  // Create the case.
  await page.getByRole("link", { name: "New case" }).first().click();
  await page.getByLabel("Title").fill("Heat sink");
  await page.getByLabel("Problem addressed").fill("Processors run too hot under sustained load.");
  await page.getByLabel("Solution and key features").fill("A fin array with a fan that spins up on demand.");
  await page.getByRole("button", { name: "Save and continue" }).click();
  await page.getByRole("button", { name: "Extract from disclosure" }).click();
  await expect(page.getByLabel("Element 2", { exact: true })).toHaveValue("a controller reducing charge current");
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByLabel("Language model mode for this case").selectOption("local_only");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByText("Nothing will leave this server")).toBeVisible();

  // Run and watch progress.
  await page.getByRole("button", { name: "Run analysis" }).click();
  await expect(page.getByText("The analysis is complete.")).toBeVisible();
  await expect(page.getByText("2,400")).toBeVisible();

  // Read the chart with the keyboard, then override a cell with a reason.
  await page.getByRole("link", { name: "Open the claim chart" }).click();
  await expect(page.getByRole("heading", { name: /US100A1/ })).toBeVisible();
  await expect(page.locator("blockquote")).toContainText("A thermistor senses cell temperature.");
  await page.locator("#el-btn-E1").focus();
  await page.keyboard.press("j");
  await expect(page.locator("#el-btn-E2")).toHaveAttribute("aria-current", "true");
  await page.keyboard.press("2");
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Reason (required)").fill("The controller is described in the background section.");
  await dialog.getByRole("button", { name: "Save override" }).click();
  await expect(page.getByText(/Reviewer reason: The controller is described/)).toBeVisible();

  // Accessibility of the signature screen.
  const axe = await new AxeBuilder({ page }).disableRules(["color-contrast"]).analyze();
  expect(axe.violations.map((v) => v.id)).toEqual([]);

  // Report, review, approval and export.
  await page.getByRole("tab", { name: "Risk report" }).click();
  await expect(page.getByRole("figure", { name: "Risk score 80 out of 100" })).toBeVisible();
  await page.getByRole("button", { name: "Submit for review" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Submit for review" }).click();
  await expect(page.getByText("Submitted for review")).toBeVisible();
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(page.getByText(/cannot be undone/)).toBeVisible();
  await page.getByRole("dialog").getByRole("button", { name: "Approve report" }).click();
  await expect(page.getByText("Report approved")).toBeVisible();

  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export PDF" }).click();
  expect((await download).suggestedFilename()).toBe("report-c1.pdf");

  // A reload keeps the session through the refresh cookie, and logging out ends it.
  await page.reload();
  await expect(page.getByRole("heading", { name: "Heat sink" })).toBeVisible();
  await page.getByRole("button", { name: "Account menu" }).click();
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.goto("/app");
  await expect(page).toHaveURL(/\/login$/);
  expect(state.log).toContain("PATCH /chart/cells/k2");
});

test("the claim chart fits a phone screen without sideways scrolling", async ({ page }) => {
  await mockApi(page, true);
  await page.setViewportSize({ width: 360, height: 800 });
  await page.goto("/login");
  await page.getByLabel("Email").fill("attorney@example.com");
  await page.getByLabel("Password").fill("correct horse");
  await page.getByRole("button", { name: "Log in" }).click();
  await page.getByRole("heading", { name: /Welcome/ }).waitFor();
  await page.goto("/app/cases/c1?tab=chart");
  await expect(page.getByRole("heading", { name: /US100A1/ })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

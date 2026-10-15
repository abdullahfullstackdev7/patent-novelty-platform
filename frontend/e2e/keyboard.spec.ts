import { expect, test, type Page } from "@playwright/test";

import { mockApi } from "./mockApi";

// The manual keyboard pass, automated: every step below uses the keyboard only (no mouse clicks).

async function hasVisibleFocus(page: Page) {
  return page.evaluate(() => {
    const el = document.activeElement as HTMLElement | null;
    if (!el || el === document.body) return false;
    const style = getComputedStyle(el);
    const ring = style.boxShadow !== "none" && style.boxShadow !== "";
    const outline = style.outlineStyle !== "none" && parseFloat(style.outlineWidth) > 0;
    return ring || outline;
  });
}

test("the skip link is the first stop and moves focus to the page content", async ({ page }) => {
  await page.goto("/pricing");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to main content" })).toBeFocused();
  expect(await hasVisibleFocus(page)).toBe(true);
  await page.keyboard.press("Enter");
  await expect(page.locator("main")).toBeFocused();
});

test("the Log in link is reachable by keyboard and opens the login page", async ({ page }) => {
  await page.goto("/");
  for (let i = 0; i < 40; i++) {
    await page.keyboard.press("Tab");
    const name = await page.evaluate(() => (document.activeElement as HTMLElement | null)?.textContent?.trim() ?? "");
    if (name === "Log in") break;
  }
  await expect(page.getByRole("banner").getByRole("link", { name: "Log in" })).toBeFocused();
  expect(await hasVisibleFocus(page)).toBe(true);
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/login$/);
});

test("a mega menu opens with the keyboard and closes with Escape", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");
  const trigger = page.getByRole("button", { name: "Platform" }).first();
  await trigger.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("link", { name: /Claim charts/ }).first()).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("link", { name: /Claim charts/ }).first()).toBeHidden();
});

test("signing in and reaching the claim chart needs no mouse, and the override dialog traps focus", async ({ page }) => {
  await mockApi(page, true);
  await page.goto("/login");
  await page.getByLabel("Email").focus();
  await page.keyboard.type("attorney@example.com");
  await page.keyboard.press("Tab");
  await page.keyboard.type("correct horse");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: /Welcome/ })).toBeVisible();

  await page.goto("/app/cases/c1?tab=chart");
  await expect(page.getByRole("heading", { name: /US100A1/ })).toBeVisible();
  await page.locator("#el-btn-E1").focus();
  expect(await hasVisibleFocus(page)).toBe(true);
  await page.keyboard.press("j");
  await expect(page.locator("#el-btn-E2")).toHaveAttribute("aria-current", "true");
  await page.keyboard.press("1");
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  for (let i = 0; i < 8; i++) {
    await page.keyboard.press("Tab");
    expect(await page.evaluate(() => !!document.activeElement?.closest('[role="dialog"]'))).toBe(true);
  }
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
});

test("people who prefer reduced motion see all content straight away", async ({ browser }) => {
  const context = await browser.newContext({ reducedMotion: "reduce" });
  const page = await context.newPage();
  await page.goto("/");
  const hidden = await page.evaluate(() => [...document.querySelectorAll("main *")].filter((el) => getComputedStyle(el).opacity === "0").length);
  expect(hidden).toBe(0);
  await context.close();
});

test("zooming to 200 percent keeps the page free of sideways scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 640, height: 800 }); // 1280 px at 200 percent zoom
  for (const path of ["/", "/pricing", "/contact", "/login"]) {
    await page.goto(path);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, path).toBeLessThanOrEqual(1);
  }
});

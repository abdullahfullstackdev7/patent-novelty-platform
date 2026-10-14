import * as NavigationMenu from "@radix-ui/react-navigation-menu";
import { ChevronDown, Menu } from "lucide-react";
import { useState } from "react";
import { Link, NavLink as RouterLink } from "react-router-dom";

import { Container } from "@/components/site/primitives";
import { Button } from "@/components/ui/button";
import { Sheet, SheetClose, SheetContent, SheetTrigger, DialogTitle, DialogDescription } from "@/components/ui/overlay";
import { NAV, type NavLink } from "@/content/site";

export function Logo({ light = false }: { light?: boolean }) {
  return (
    <Link to="/" className="flex items-center gap-2 font-semibold" aria-label="PriorArt Atlas home">
      <svg width="28" height="28" viewBox="0 0 32 32" aria-hidden="true">
        <rect width="32" height="32" rx="7" fill={light ? "#fff" : "#0B1F3A"} />
        <circle cx="14" cy="14" r="6" fill="none" stroke={light ? "#0B1F3A" : "#fff"} strokeWidth="2.5" />
        <path d="M19 19l6 6" stroke="#0E7C86" strokeWidth="3" strokeLinecap="round" />
      </svg>
      <span className={light ? "text-white" : "text-navy"}>PriorArt Atlas</span>
    </Link>
  );
}

const MENUS: { label: string; links: NavLink[] }[] = [
  { label: "Platform", links: NAV.platform },
  { label: "Solutions", links: NAV.solutions },
  { label: "Resources", links: NAV.resources },
  { label: "Company", links: NAV.company },
];

function MegaMenu() {
  return (
    <NavigationMenu.Root className="relative hidden lg:block" aria-label="Main">
      <NavigationMenu.List className="flex items-center gap-1">
        {MENUS.map((menu) => (
          <NavigationMenu.Item key={menu.label}>
            <NavigationMenu.Trigger className="group flex items-center gap-1 rounded-md px-3 py-2 text-base font-medium text-navy hover:bg-navy-50">
              {menu.label}
              <ChevronDown className="h-4 w-4 transition-transform group-data-[state=open]:rotate-180" aria-hidden="true" />
            </NavigationMenu.Trigger>
            <NavigationMenu.Content className="absolute left-0 top-full">
              <ul className="grid w-[26rem] gap-1 p-3">
                {menu.links.map((link) => (
                  <li key={link.to}>
                    <NavigationMenu.Link asChild>
                      <Link to={link.to} className="block rounded-lg p-3 hover:bg-navy-50">
                        <span className="block font-semibold text-navy">{link.label}</span>
                        {link.description && <span className="mt-0.5 block text-sm text-stone-600">{link.description}</span>}
                      </Link>
                    </NavigationMenu.Link>
                  </li>
                ))}
              </ul>
            </NavigationMenu.Content>
          </NavigationMenu.Item>
        ))}
        <NavigationMenu.Item>
          <NavigationMenu.Link asChild>
            <RouterLink to="/pricing" className="rounded-md px-3 py-2 text-base font-medium text-navy hover:bg-navy-50">
              Pricing
            </RouterLink>
          </NavigationMenu.Link>
        </NavigationMenu.Item>
      </NavigationMenu.List>
      <div className="absolute left-0 top-full flex w-full justify-start">
        <NavigationMenu.Viewport className="mt-1 overflow-hidden rounded-xl border border-stone-200 bg-white shadow-card" />
      </div>
    </NavigationMenu.Root>
  );
}

function MobileMenu() {
  const [open, setOpen] = useState(false);
  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button variant="ghost" size="sm" className="lg:hidden" aria-label="Open menu">
          <Menu className="h-6 w-6" aria-hidden="true" />
        </Button>
      </SheetTrigger>
      <SheetContent>
        <DialogTitle className="text-lg font-semibold text-navy">Menu</DialogTitle>
        <DialogDescription className="sr-only">Site navigation</DialogDescription>
        <nav aria-label="Mobile" className="mt-6 space-y-6">
          {MENUS.map((menu) => (
            <div key={menu.label}>
              <p className="mb-2 text-sm font-semibold uppercase tracking-wider text-stone-600">{menu.label}</p>
              <ul className="space-y-1">
                {menu.links.map((link) => (
                  <li key={link.to}>
                    <SheetClose asChild>
                      <Link to={link.to} className="block rounded-md px-2 py-2 text-base text-navy hover:bg-navy-50">
                        {link.label}
                      </Link>
                    </SheetClose>
                  </li>
                ))}
              </ul>
            </div>
          ))}
          <SheetClose asChild>
            <Link to="/pricing" className="block rounded-md px-2 py-2 font-semibold text-navy hover:bg-navy-50">
              Pricing
            </Link>
          </SheetClose>
          <div className="flex flex-col gap-3 pt-2">
            <SheetClose asChild>
              <Button asChild variant="outline">
                <Link to="/login">Log in</Link>
              </Button>
            </SheetClose>
            <SheetClose asChild>
              <Button asChild>
                <Link to="/contact?topic=demo">Request a demo</Link>
              </Button>
            </SheetClose>
          </div>
        </nav>
      </SheetContent>
    </Sheet>
  );
}

export function Header() {
  return (
    <>
      <div className="hidden bg-navy text-sm text-navy-100 md:block">
        <Container className="flex h-9 items-center justify-end gap-6">
          <Link to="/contact?topic=sales" className="hover:text-white">
            Contact sales
          </Link>
          <Link to="/contact?topic=support" className="hover:text-white">
            Support
          </Link>
          <span aria-label="Language: English">EN</span>
        </Container>
      </div>
      <header className="sticky top-0 z-40 border-b border-stone-200 bg-white/95 backdrop-blur">
        <Container className="flex h-16 items-center justify-between gap-4">
          <div className="flex items-center gap-8">
            <Logo />
            <MegaMenu />
          </div>
          <div className="flex items-center gap-2">
            <Button asChild variant="outline" size="sm" className="hidden sm:inline-flex">
              <Link to="/login">Log in</Link>
            </Button>
            <Button asChild size="sm" className="hidden sm:inline-flex">
              <Link to="/contact?topic=demo">Request a demo</Link>
            </Button>
            <MobileMenu />
          </div>
        </Container>
      </header>
    </>
  );
}

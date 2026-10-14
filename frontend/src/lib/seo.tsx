import { useEffect } from "react";

export const SITE_URL = "https://priorart-atlas.example";
const SUFFIX = "PriorArt Atlas";

function setMeta(selector: string, attr: "name" | "property", key: string, value: string) {
  let el = document.head.querySelector<HTMLMetaElement>(selector);
  if (!el) {
    el = document.createElement("meta");
    el.setAttribute(attr, key);
    document.head.appendChild(el);
  }
  el.setAttribute("content", value);
}

export function applySeo(title: string, description: string, path: string) {
  const full = title === SUFFIX ? title : `${title} | ${SUFFIX}`;
  document.title = full;
  setMeta('meta[name="description"]', "name", "description", description);
  setMeta('meta[property="og:title"]', "property", "og:title", full);
  setMeta('meta[property="og:description"]', "property", "og:description", description);
  setMeta('meta[property="og:url"]', "property", "og:url", `${SITE_URL}${path}`);
  let link = document.head.querySelector<HTMLLinkElement>('link[rel="canonical"]');
  if (!link) {
    link = document.createElement("link");
    link.rel = "canonical";
    document.head.appendChild(link);
  }
  link.href = `${SITE_URL}${path}`;
}

/** Sets the document title, description, canonical URL and Open Graph tags for the page. */
export function Seo({ title, description, path }: { title: string; description: string; path: string }) {
  useEffect(() => applySeo(title, description, path), [title, description, path]);
  return null;
}

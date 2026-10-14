import { useParams } from "react-router-dom";

import { Container, PageHero } from "@/components/site/primitives";
import { Seo } from "@/lib/seo";
import NotFound from "@/pages/NotFound";

interface LegalPage {
  title: string;
  summary: string;
  body: { heading: string; text: string }[];
}

const NOTICE =
  "This text is a working draft prepared for the demonstration build. It must be reviewed by counsel before the service is offered to customers.";

export const LEGAL: Record<string, LegalPage> = {
  privacy: {
    title: "Privacy Policy",
    summary: "What personal data the service handles and why.",
    body: [
      { heading: "Data we collect", text: "Account details (name, work email, role), content you submit (invention disclosures, case notes), usage records needed to operate and bill the service, and messages you send through the contact form." },
      { heading: "How we use it", text: "To provide the service, secure accounts, meter usage for invoicing, respond to enquiries and improve reliability. Disclosures are not used to train models." },
      { heading: "Third-party processors", text: "When a cloud language model is enabled, the minimum text needed for a task is sent to the configured provider. In local-only mode no text leaves your infrastructure." },
      { heading: "Retention and deletion", text: "Each case has a retention period set by your administrator. Expired cases can be purged, and contact-form messages are kept only as long as needed to respond." },
      { heading: "Your rights", text: "You may ask to access, correct or delete personal data we hold about you by writing to us through the contact form." },
    ],
  },
  terms: {
    title: "Terms of Use",
    summary: "The rules for using the website and the service.",
    body: [
      { heading: "The service", text: "PriorArt Atlas provides decision support for prior-art review. Outputs are not legal advice and do not replace the judgment of a qualified professional." },
      { heading: "Accounts", text: "You are responsible for activity under your account and for keeping credentials confidential. Report suspected misuse promptly." },
      { heading: "Acceptable use", text: "Do not attempt to disrupt the service, access data you are not authorised to see, or submit content you have no right to share." },
      { heading: "Availability and liability", text: "The service is provided as available, without guarantee of completeness of search results. Liability is limited to the extent permitted by law." },
    ],
  },
  cookies: {
    title: "Cookie Notice",
    summary: "How cookies and local storage are used.",
    body: [
      { heading: "Essential cookies", text: "After you sign in, a secure, HTTP-only cookie keeps your session alive. It is not readable by scripts on the page." },
      { heading: "No advertising or analytics cookies", text: "The public website does not set advertising or third-party analytics cookies." },
      { heading: "Local storage", text: "If you enter an email in the newsletter field, it is stored in your own browser only, because no mailing list exists yet." },
    ],
  },
  accessibility: {
    title: "Accessibility Statement",
    summary: "Our commitment to an accessible website.",
    body: [
      { heading: "Our target", text: "We design to the Web Content Accessibility Guidelines (WCAG) 2.1 level AA: keyboard operation, visible focus, sufficient contrast, semantic landmarks and support for reduced motion." },
      { heading: "Known limitations", text: "The demonstration build has not had a full manual audit with assistive technology. Automated checks run on every release." },
      { heading: "Feedback", text: "If you meet a barrier, tell us through the contact form and we will respond with a fix or an alternative." },
    ],
  },
  attributions: {
    title: "Attributions",
    summary: "Data sources and open-source credits.",
    body: [
      { heading: "PatentsView", text: "Granted patent data comes from PatentsView, a USPTO initiative, licensed under Creative Commons Attribution 4.0 International (CC BY 4.0)." },
      { heading: "Harvard USPTO Patent Dataset (HUPD)", text: "Patent application data comes from HUPD, licensed under Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)." },
      { heading: "Software and typefaces", text: "Built with React, Tailwind CSS, Radix UI, lucide icons, Inter (SIL Open Font License) and IBM Plex Mono (SIL Open Font License). Illustrations on this site are original." },
    ],
  },
};

export default function Legal() {
  const { doc } = useParams();
  const page = doc ? LEGAL[doc] : undefined;
  if (!page) return <NotFound />;
  return (
    <>
      <Seo title={page.title} description={page.summary} path={`/legal/${doc}`} />
      <PageHero eyebrow="Legal" title={page.title} intro={page.summary} />
      <Container className="py-12">
        <div className="prose-article mx-auto max-w-2xl">
          <p className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-base text-risk-medium">{NOTICE}</p>
          {page.body.map((s) => (
            <section key={s.heading}>
              <h2>{s.heading}</h2>
              <p>{s.text}</p>
            </section>
          ))}
        </div>
      </Container>
    </>
  );
}

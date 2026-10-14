import { Link } from "react-router-dom";

import { ClaimChartMock, TourPanel } from "@/components/site/ProductMock";
import { Container, CtaBanner, PageHero, Reveal } from "@/components/site/primitives";
import { Button } from "@/components/ui/button";
import { Seo } from "@/lib/seo";

const DEEP_DIVES = [
  {
    id: "search",
    title: "Hybrid search that understands meaning and keeps exact terms",
    text: "Each query runs two retrievers in parallel. A vector index finds passages that mean the same thing as your claim element, even when the wording differs. A full-text index finds the exact phrases and part numbers you typed. The two ranked lists are merged with reciprocal rank fusion and then reranked by a cross-encoder that reads the query and passage together. Classification voting highlights the CPC groups where the best matches cluster, so you can widen or narrow the search by technical area.",
    points: ["Semantic and keyword retrieval, merged and reranked", "Filters for date and source", "CPC voting to focus on the right technical area"],
    visual: <TourPanel title="Search results" rows={["US10234567B2  Adaptive battery thermal controller", "US9876543B2  Cell temperature estimation method", "US11002233B1  Pack cooling manifold"]} />,
  },
  {
    id: "charts",
    title: "Claim charts with evidence you can check",
    text: "After you confirm the elements of your claim, the platform compares each element with the closest references and rates the coverage. Every rating is paired with a passage copied from the reference. Before a passage is displayed it is matched against the source text, and any passage that cannot be found word for word is discarded. Reruns reuse cells whose inputs have not changed, so edits are fast and consistent.",
    points: ["Disclosed, partial or absent for every cell", "Verbatim excerpts verified against the source", "Reruns only recompute what changed"],
    visual: <ClaimChartMock />,
  },
  {
    id: "risk",
    title: "Risk levels from transparent rules",
    text: "Novelty and obviousness risk are derived from the chart with fixed, documented rules: a single reference covering every element drives novelty risk, while a small set of references that together cover the claim in one technical area drives obviousness risk. Because the rules are deterministic, the same chart always yields the same level, and the report explains how it was reached.",
    points: ["Deterministic, explainable risk scoring", "Closest references and uncovered elements called out", "Language models assist with charting, not with the final level"],
    visual: <TourPanel title="Risk report" rows={["Novelty risk        Medium", "Obviousness risk    Low", "Closest reference   US10234567B2"]} />,
  },
  {
    id: "review",
    title: "Review, sign-off and reports",
    text: "Cases move through draft, in review and signed off. Reviewers can comment on any rating, adjust it and record the reason. The administrator role cannot sign a report on a reviewer's behalf, so the sign-off always reflects a named professional. Reports are versioned and can be downloaded as PDF.",
    points: ["Comments, adjustments and sign-off recorded with who and when", "Versioned reports with PDF export", "Case sharing with role-based access"],
    visual: <TourPanel title="Review history" rows={["Analyst   drafted report v1", "Attorney  adjusted element 3 to Partial", "Attorney  signed off v2"]} />,
  },
];

export default function Platform() {
  return (
    <>
      <Seo title="Platform" description="Hybrid search, claim charts with verbatim evidence, transparent risk scoring and a review workflow in one platform." path="/platform" />
      <PageHero
        eyebrow="Platform"
        title="One workflow from invention disclosure to signed-off report"
        intro="Search, chart, assess and review without moving data between tools or losing the evidence behind a conclusion."
      />
      <Container className="space-y-20 py-16 md:space-y-28 md:py-24">
        {DEEP_DIVES.map((item, i) => (
          <section key={item.id} id={item.id} aria-labelledby={`${item.id}-title`} className="grid items-center gap-10 lg:grid-cols-2">
            <Reveal className={i % 2 ? "lg:order-2" : ""}>
              <h2 id={`${item.id}-title`} className="text-xl md:text-2xl">
                {item.title}
              </h2>
              <p className="mt-4 text-lg text-stone-700">{item.text}</p>
              <ul className="mt-5 space-y-2 text-base text-stone-700">
                {item.points.map((p) => (
                  <li key={p} className="flex gap-2">
                    <span aria-hidden="true" className="mt-2.5 h-1.5 w-1.5 shrink-0 rounded-full bg-teal-600" />
                    {p}
                  </li>
                ))}
              </ul>
            </Reveal>
            <Reveal className={i % 2 ? "lg:order-1" : ""}>{item.visual}</Reveal>
          </section>
        ))}
        <p className="text-center">
          <Button asChild variant="outline">
            <Link to="/pricing">See pricing</Link>
          </Button>
        </p>
      </Container>
      <CtaBanner title="Run a sample case with your own claims" text="We will walk through a disclosure, a chart and a report together." />
    </>
  );
}

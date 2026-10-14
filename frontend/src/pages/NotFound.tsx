import { Link } from "react-router-dom";

import { Container } from "@/components/site/primitives";
import { Button } from "@/components/ui/button";
import { Seo } from "@/lib/seo";

export default function NotFound() {
  return (
    <>
      <Seo title="Page not found" description="The page you are looking for does not exist." path="/404" />
      <Container className="py-24 text-center">
        <p className="eyebrow">Error 404</p>
        <h1 className="text-2xl md:text-3xl">We could not find that page</h1>
        <p className="mx-auto mt-4 max-w-md text-lg text-stone-700">The address may be mistyped, or the page may have moved.</p>
        <div className="mt-8 flex justify-center gap-3">
          <Button asChild>
            <Link to="/">Go to the home page</Link>
          </Button>
          <Button asChild variant="outline">
            <Link to="/contact">Contact us</Link>
          </Button>
        </div>
      </Container>
    </>
  );
}

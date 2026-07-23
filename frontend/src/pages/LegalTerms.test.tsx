import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { MemoryRouter, Route, Routes } from "react-router-dom"

import LegalTerms from "./LegalTerms"

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/legal/terms"]}>
      <Routes>
        <Route path="/legal/terms" element={<LegalTerms />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe("LegalTerms", () => {
  it("renders every section of the Terms of Service", () => {
    renderPage()

    expect(
      screen.getByRole("heading", { name: "Terms of Service" }),
    ).toBeInTheDocument()

    // Every section renders — a missing section is a policy change, not a
    // styling tweak.
    for (const section of [
      /eligibility/i,
      /the service/i,
      /accounts/i,
      /your content/i,
      /ai-generated content/i,
      /optional integrations/i,
      /credits and billing/i,
      /acceptable use/i,
      /intellectual property/i,
      /termination/i,
      /disclaimers and limitation of liability/i,
      /third-party services/i,
      /governing law/i,
      /changes to these terms/i,
      /\bcontact\b/i,
    ]) {
      expect(screen.getByRole("heading", { name: section })).toBeInTheDocument()
    }
  })

  it("discloses the Razorpay non-Merchant-of-Record and refund-debt facts", () => {
    const { container } = renderPage()
    const text = container.textContent ?? ""
    // Markdown bold ("**not**") splits the sentence across elements, so
    // assert on the full rendered text rather than a single text node.
    expect(text).toMatch(/Razorpay.*is.*not.*the Merchant of Record/s)
    expect(text).toMatch(/recoverable billing debt/i)
  })

  it("links to the Privacy Policy and Data Retention Policy", () => {
    renderPage()
    for (const link of screen.getAllByRole("link", { name: "Privacy Policy" })) {
      expect(link).toHaveAttribute("href", "/legal/privacy")
    }
    for (const link of screen.getAllByRole("link", {
      name: /data retention policy/i,
    })) {
      expect(link).toHaveAttribute("href", "/legal/retention")
    }
  })

  it("links back to the app root", () => {
    renderPage()
    expect(screen.getByRole("link", { name: /back to thought2build/i })).toHaveAttribute(
      "href",
      "/",
    )
  })
})

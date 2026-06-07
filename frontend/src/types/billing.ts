export interface BillingPackage {
  credits: number
  price_cents: number
  validity_days: number
  currency: string
}

export interface BillingCreditPack {
  id: string
  credits_purchased: number
  credits_remaining: number
  price_cents: number
  status: "active" | "consumed" | "expired" | "refunded" | "disputed"
  purchased_at: string
  expires_at: string
}

export interface BillingStatusResponse {
  status: "pending" | "completed"
  credits_added: number
  expires_at: string | null
}

export interface CheckoutResponse {
  checkout_url: string
  checkout_ref: string
}

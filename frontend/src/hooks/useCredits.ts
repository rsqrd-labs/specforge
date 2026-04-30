import { useEffect, useState } from "react"
import { getCredits } from "../services/api"

export function useCredits() {
  const [balance, setBalance] = useState<number | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    let cancelled = false

    async function fetchBalance() {
      try {
        const result = await getCredits()
        if (!cancelled) {
          setBalance(result.balance)
        }
      } catch {
        if (!cancelled) {
          setBalance(null)
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false)
        }
      }
    }

    void fetchBalance()
    const interval = window.setInterval(fetchBalance, 30_000)

    return () => {
      cancelled = true
      window.clearInterval(interval)
    }
  }, [])

  return { balance, isLoading }
}

import * as Sentry from "@sentry/react"
import ReactDOM from "react-dom/client"

import App from "./App"
import "./index.css"

if (import.meta.env.VITE_SENTRY_DSN) {
  Sentry.init({
    dsn: import.meta.env.VITE_SENTRY_DSN,
    integrations: [Sentry.browserTracingIntegration()],
    tracesSampleRate: 0.1,
  })
}

ReactDOM.createRoot(document.getElementById("root")!).render(<App />)

import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"
import {
  ActionAlertPanel,
  ActionAlertProvider,
  useActionAlert,
} from "./ActionAlert"

function AlertLauncher({
  onPrimary,
  autoDismiss = true,
}: {
  onPrimary: () => void
  autoDismiss?: boolean
}) {
  const { showAlert } = useActionAlert()
  return (
    <button
      type="button"
      onClick={() =>
        showAlert({
          severity: "error",
          title: "Generation timed out",
          message: "The model did not finish in time.",
          recovery: "Try again; your workspace is safe.",
          source: "Generation",
          primaryAction: {
            label: "Try again",
            onSelect: onPrimary,
            autoDismiss,
          },
        })
      }
    >
      Show alert
    </button>
  )
}

describe("ActionAlertProvider", () => {
  it("renders an accessible alert dialog with recovery copy and actions", async () => {
    const user = userEvent.setup()
    const onPrimary = vi.fn()
    render(
      <ActionAlertProvider>
        <AlertLauncher onPrimary={onPrimary} />
      </ActionAlertProvider>,
    )

    await user.click(screen.getByRole("button", { name: /show alert/i }))

    const dialog = screen.getByRole("alertdialog")
    expect(dialog).toHaveTextContent("Generation timed out")
    expect(dialog).toHaveTextContent("The model did not finish in time.")
    expect(dialog).toHaveTextContent("Try again; your workspace is safe.")
    expect(screen.getByRole("button", { name: /dismiss alert/i })).toHaveFocus()

    await user.click(screen.getByRole("button", { name: /try again/i }))
    expect(onPrimary).toHaveBeenCalledOnce()
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument()
  })

  it("closes the dialog on Escape", async () => {
    const user = userEvent.setup()
    render(
      <ActionAlertProvider>
        <AlertLauncher onPrimary={vi.fn()} />
      </ActionAlertProvider>,
    )

    await user.click(screen.getByRole("button", { name: /show alert/i }))
    expect(screen.getByRole("alertdialog")).toBeInTheDocument()

    await user.keyboard("{Escape}")
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument()
  })

  it("keeps non-auto-dismiss actions visible until dismissed", async () => {
    const user = userEvent.setup()
    render(
      <ActionAlertProvider>
        <AlertLauncher onPrimary={vi.fn()} autoDismiss={false} />
      </ActionAlertProvider>,
    )

    await user.click(screen.getByRole("button", { name: /show alert/i }))
    await user.click(screen.getByRole("button", { name: /try again/i }))

    expect(screen.getByRole("alertdialog")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: /^dismiss$/i }))
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument()
  })
})

describe("ActionAlertPanel", () => {
  it("renders panel errors with alert semantics and dismiss callbacks", async () => {
    const user = userEvent.setup()
    const onDismiss = vi.fn()
    render(
      <ActionAlertPanel
        severity="error"
        title="Checkout could not open"
        message="Your credits were not charged."
        recovery="Try again from Billing."
        source="Billing"
        onDismiss={onDismiss}
      />,
    )

    const panel = screen.getByRole("alert")
    expect(panel).toHaveTextContent("Checkout could not open")
    expect(panel).toHaveTextContent("Your credits were not charged.")

    await user.click(screen.getByRole("button", { name: /dismiss/i }))
    expect(onDismiss).toHaveBeenCalledOnce()
  })
})

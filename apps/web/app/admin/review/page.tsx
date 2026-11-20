"use client";

import { useCallback, useState } from "react";

import { AdminPage } from "@/components/admin/AdminPage";
import { ActionError, Loaded } from "@/components/Feedback";
import type { Session } from "@/components/RoleShell";
import { Button } from "@/components/ui/Button";
import { Badge, Card, CardBody } from "@/components/ui/Card";
import { Field, SelectInput, TextArea } from "@/components/ui/Field";
import { EmptyState } from "@/components/ui/States";
import { useAction, useResource } from "@/lib/hooks";
import { adminApi, type ReviewCase } from "@/lib/market";

const ACTIONS: Record<string, string[]> = {
  account: ["none", "suspend_account"],
  listing: ["none", "pause_listing"],
  order: ["none"],
};

function CaseRow({
  item,
  token,
  reload,
}: {
  item: ReviewCase;
  token: string;
  reload: () => Promise<void>;
}) {
  const action = useAction();
  const [note, setNote] = useState("");
  const [chosen, setChosen] = useState("none");

  const decide = (outcome: "cleared" | "actioned") =>
    void action.run(async () => {
      await adminApi.decideCase(token, item.id, {
        outcome,
        action: outcome === "cleared" ? "none" : chosen,
        note,
      });
      await reload();
    });

  return (
    <Card>
      <CardBody>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={item.score >= 70 ? "danger" : "warn"}>Score {item.score}</Badge>
          <Badge>{item.subject_type}</Badge>
          <span className="font-mono text-xs text-ink-faint">{item.subject_id}</span>
        </div>
        <ul className="mt-2 list-disc ps-5 text-sm">
          {item.signals.map((signal) => (
            <li key={signal.code}>
              {signal.detail} <span className="text-ink-faint">(+{signal.weight})</span>
            </li>
          ))}
        </ul>
        <div className="mt-3 grid gap-3 md:grid-cols-[1fr_14rem]">
          <Field label="Why" htmlFor={`note-${item.id}`}>
            <TextArea
              id={`note-${item.id}`}
              rows={2}
              value={note}
              onChange={(event) => setNote(event.target.value)}
            />
          </Field>
          <Field label="Action if acting" htmlFor={`action-${item.id}`}>
            <SelectInput
              id={`action-${item.id}`}
              value={chosen}
              onChange={(event) => setChosen(event.target.value)}
            >
              {(ACTIONS[item.subject_type] ?? ["none"]).map((value) => (
                <option key={value} value={value}>
                  {value.replace("_", " ")}
                </option>
              ))}
            </SelectInput>
          </Field>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            variant="secondary"
            loading={action.busy}
            disabled={note.trim().length < 3}
            onClick={() => decide("cleared")}
          >
            Clear
          </Button>
          <Button
            loading={action.busy}
            disabled={note.trim().length < 3}
            onClick={() => decide("actioned")}
          >
            Act
          </Button>
        </div>
        <ActionError message={action.error} />
      </CardBody>
    </Card>
  );
}

function Review({ session }: { session: Session }) {
  const { token, locale } = session;
  const action = useAction();
  const cases = useResource(useCallback(() => adminApi.reviewCases(token), [token]));
  return (
    <>
      <div className="mb-4">
        <Button
          variant="secondary"
          loading={action.busy}
          onClick={() =>
            void action.run(async () => {
              await adminApi.runRisk(token);
              await cases.reload();
            })
          }
        >
          Score now
        </Button>
        <ActionError message={action.error} />
      </div>
      <Loaded resource={cases} locale={locale}>
        {(items) =>
          items.length === 0 ? (
            <EmptyState title="No open cases." />
          ) : (
            <ul className="space-y-4">
              {items.map((item) => (
                <li key={item.id}>
                  <CaseRow item={item} token={token} reload={cases.reload} />
                </li>
              ))}
            </ul>
          )
        }
      </Loaded>
    </>
  );
}

export default function AdminReviewPage() {
  return (
    <AdminPage
      title="Risk review"
      subtitle="Flags from rules and the AI risk check. Only a person clears or acts on one."
    >
      {(session) => <Review session={session} />}
    </AdminPage>
  );
}

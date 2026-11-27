"use client";

/**
 * The assistant chat, shared by the buyer assistant and the brand assistant.
 *
 * The two differ only in where messages go and what the page says about the
 * assistant's limits, so both are props and everything else is one component.
 */

import Link from "next/link";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";

import { ActionError, PageHeader } from "@/components/Feedback";
import { type Session } from "@/components/RoleShell";
import { Button } from "@/components/ui/Button";
import { Badge, Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { Field, TextArea } from "@/components/ui/Field";
import { Skeleton } from "@/components/ui/States";
import { dateTime } from "@/lib/format";
import { useAction, useFeatures, useResource } from "@/lib/hooks";
import { t, type Locale } from "@/lib/i18n";
import {
  type ChatExchange,
  type ChatMessage,
  type Conversation,
  type ConversationDetail,
} from "@/lib/market";

export type ChatApi = {
  list: (token: string) => Promise<Conversation[]>;
  detail: (token: string, id: string) => Promise<ConversationDetail>;
  send: (token: string, message: string, conversationId?: string) => Promise<ChatExchange>;
  usage: (token: string) => Promise<{ remaining: number; limit: number }>;
};

export type ChatCopy = {
  title: string;
  subtitle: string;
  limits: string;
  start: string;
};

function Bubble({ message, locale }: { message: ChatMessage; locale: Locale }) {
  const mine = message.role === "buyer";
  // Each message keeps its own direction, so a Roman Urdu reply inside the
  // Urdu interface still reads left to right.
  const dir = message.language === "ur" ? "rtl" : message.language ? "ltr" : "auto";
  return (
    <li className={`flex ${mine ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] rounded-lg px-4 py-3 ${
          mine ? "bg-brand text-white" : "border border-line bg-surface"
        }`}
      >
        <p className="mb-1 text-xs font-semibold opacity-80">
          {t(locale, mine ? "assistant.you" : "assistant.bot")}
          <span className="ms-2 font-normal">{dateTime(message.created_at)}</span>
        </p>
        <p dir={dir} className="whitespace-pre-line break-words">
          {message.body}
        </p>
        {message.lot_codes.length > 0 ? (
          <div className="mt-2 flex flex-wrap items-center gap-1">
            <span className="text-xs text-ink-soft">{t(locale, "assistant.lots")}:</span>
            {message.lot_codes.map((code) => (
              <Badge key={code} tone="accent">
                {code}
              </Badge>
            ))}
          </div>
        ) : null}
        {message.declined ? (
          <p className="mt-2 text-xs text-ink-soft">{t(locale, "assistant.declined")}</p>
        ) : null}
      </div>
    </li>
  );
}

function ConversationList({
  items,
  activeId,
  locale,
  onPick,
  onNew,
}: {
  items: Conversation[];
  activeId: string | null;
  locale: Locale;
  onPick: (id: string) => void;
  onNew: () => void;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle as="h2">{t(locale, "assistant.conversations")}</CardTitle>
      </CardHeader>
      <CardBody>
        <Button variant="secondary" size="sm" className="mb-3 w-full" onClick={onNew}>
          {t(locale, "assistant.new")}
        </Button>
        {items.length === 0 ? (
          <p className="text-sm text-ink-soft">{t(locale, "assistant.noConversations")}</p>
        ) : (
          <ul className="space-y-1">
            {items.map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  onClick={() => onPick(item.id)}
                  aria-current={item.id === activeId ? "true" : undefined}
                  className={`w-full rounded px-2 py-2 text-start text-sm hover:bg-surface-sunk ${
                    item.id === activeId ? "bg-surface-sunk font-semibold" : ""
                  }`}
                >
                  <span className="line-clamp-2" dir="auto">
                    {item.title}
                  </span>
                  <span className="mt-0.5 flex items-center gap-2 text-xs text-ink-soft">
                    {dateTime(item.last_message_at)}
                    {item.channel === "whatsapp" ? (
                      <Badge>{t(locale, "assistant.whatsapp")}</Badge>
                    ) : null}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}

export function AssistantChat({
  session,
  chatApi,
  copy,
  showCatalogLink = false,
  showWhatsAppNote = false,
}: {
  session: Session;
  chatApi: ChatApi;
  copy: ChatCopy;
  showCatalogLink?: boolean;
  /** For buyers, who may expect the assistant on WhatsApp too. */
  showWhatsAppNote?: boolean;
}) {
  const { token, locale } = session;
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loadingThread, setLoadingThread] = useState(false);
  const [draft, setDraft] = useState("");
  const [remaining, setRemaining] = useState<{ count: number; limit: number } | null>(null);
  const action = useAction();
  const endRef = useRef<HTMLLIElement>(null);

  const list = useResource(useCallback(() => chatApi.list(token), [chatApi, token]));

  useEffect(() => {
    void chatApi
      .usage(token)
      .then((usage) => setRemaining({ count: usage.remaining, limit: usage.limit }))
      .catch(() => setRemaining(null));
  }, [chatApi, token]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [messages, action.busy]);

  const open = (id: string) => {
    setActiveId(id);
    setLoadingThread(true);
    void action
      .run(async () => {
        const detail = await chatApi.detail(token, id);
        setMessages(detail.messages);
      })
      .finally(() => setLoadingThread(false));
  };

  const startNew = () => {
    setActiveId(null);
    setMessages([]);
    action.setError(null);
  };

  const send = (event?: FormEvent) => {
    event?.preventDefault();
    const text = draft.trim();
    if (!text || action.busy) return;
    void action.run(async () => {
      const exchange = await chatApi.send(token, text, activeId ?? undefined);
      setDraft("");
      setActiveId(exchange.conversation.id);
      setMessages((current) => [...current, exchange.buyer_message, exchange.reply]);
      setRemaining({ count: exchange.usage.remaining, limit: exchange.usage.limit });
      await list.reload();
    });
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter sends, Shift and Enter adds a line, as in WhatsApp on the web.
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      send();
    }
  };

  const outOfMessages = remaining !== null && remaining.count === 0;
  const features = useFeatures();
  // The assistant still answers when no model can be called, with a fixed
  // reply saying what works by hand; this says so before anyone asks.
  const aiNotice =
    features === null || features.ai.available_today
      ? null
      : t(locale, features.ai.enabled ? "feature.aiResting" : "feature.aiOff");

  return (
    <>
      <PageHeader title={copy.title} subtitle={copy.subtitle} />
      {aiNotice ? (
        <p role="status" className="mb-4 rounded border border-line bg-surface p-3 text-sm">
          {aiNotice}
        </p>
      ) : null}
      {features && !features.whatsapp && showWhatsAppNote ? (
        <p className="mb-4 text-sm text-ink-soft">{t(locale, "feature.whatsappOff")}</p>
      ) : null}
      <div className="grid gap-6 lg:grid-cols-[18rem_1fr]">
        <div className="order-2 lg:order-1">
          <ConversationList
            items={list.data ?? []}
            activeId={activeId}
            locale={locale}
            onPick={open}
            onNew={startNew}
          />
        </div>

        <Card className="order-1 lg:order-2">
          <CardBody>
            <p className="mb-4 rounded bg-surface-sunk px-3 py-2 text-sm text-ink-soft">
              {copy.limits}
            </p>

            <div
              className="mb-4 max-h-[60vh] min-h-[16rem] overflow-y-auto"
              aria-live="polite"
              aria-busy={action.busy || loadingThread}
            >
              {loadingThread ? (
                <Skeleton rows={4} />
              ) : messages.length === 0 ? (
                <p className="py-10 text-center text-ink-soft">{copy.start}</p>
              ) : (
                <ul className="space-y-3">
                  {messages.map((message) => (
                    <Bubble key={message.id} message={message} locale={locale} />
                  ))}
                  {action.busy ? (
                    <li className="text-sm text-ink-soft">{t(locale, "assistant.thinking")}</li>
                  ) : null}
                  <li ref={endRef} aria-hidden="true" />
                </ul>
              )}
            </div>

            <form onSubmit={send}>
              <Field
                label={t(locale, "assistant.message")}
                htmlFor="assistant-message"
                hint={
                  remaining
                    ? t(locale, "assistant.remaining", {
                        count: remaining.count,
                        limit: remaining.limit,
                      })
                    : undefined
                }
              >
                <TextArea
                  id="assistant-message"
                  dir="auto"
                  value={draft}
                  maxLength={2000}
                  disabled={outOfMessages}
                  onChange={(event) => setDraft(event.target.value)}
                  onKeyDown={onKeyDown}
                />
              </Field>
              {outOfMessages ? (
                <p className="mb-2 text-sm font-semibold text-warn">
                  {t(locale, "assistant.limitReached")}
                </p>
              ) : null}
              <div className="flex items-center justify-between gap-3">
                {showCatalogLink ? (
                  <Link href="/catalog" className="text-sm font-semibold text-accent underline">
                    {t(locale, "nav.catalog")}
                  </Link>
                ) : (
                  <span />
                )}
                <Button
                  type="submit"
                  loading={action.busy}
                  disabled={!draft.trim() || outOfMessages}
                >
                  {t(locale, "assistant.send")}
                </Button>
              </div>
              <ActionError message={action.error} />
            </form>
          </CardBody>
        </Card>
      </div>
    </>
  );
}

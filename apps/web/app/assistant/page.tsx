"use client";

import { useMemo } from "react";

import { AssistantChat, type ChatApi } from "@/components/AssistantChat";
import { RoleShell, type Session } from "@/components/RoleShell";
import { t } from "@/lib/i18n";
import { market } from "@/lib/market";

function BuyerAssistant({ session }: { session: Session }) {
  const { locale } = session;
  const chatApi = useMemo<ChatApi>(
    () => ({
      list: market.conversations,
      detail: market.conversation,
      send: (token, message, conversationId) =>
        market.sendAssistantMessage(token, { message, conversation_id: conversationId }),
      usage: market.assistantUsage,
    }),
    [],
  );
  return (
    <AssistantChat
      session={session}
      chatApi={chatApi}
      showCatalogLink
      showWhatsAppNote
      copy={{
        title: t(locale, "assistant.title"),
        subtitle: t(locale, "assistant.subtitle"),
        limits: t(locale, "assistant.limits"),
        start: t(locale, "assistant.start"),
      }}
    />
  );
}

export default function AssistantPage() {
  return (
    <RoleShell allow={["reseller"]}>{(session) => <BuyerAssistant session={session} />}</RoleShell>
  );
}

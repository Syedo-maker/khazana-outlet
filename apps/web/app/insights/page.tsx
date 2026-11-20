"use client";

import { useMemo } from "react";

import { AssistantChat, type ChatApi } from "@/components/AssistantChat";
import { PageHeader } from "@/components/Feedback";
import { RoleShell, type Session } from "@/components/RoleShell";
import { t } from "@/lib/i18n";
import { market } from "@/lib/market";

function BrandAssistant({ session, brandId }: { session: Session; brandId: string }) {
  const { locale } = session;
  const chatApi = useMemo<ChatApi>(
    () => ({
      list: (token) => market.brandConversations(token, brandId),
      detail: (token, id) => market.brandConversation(token, brandId, id),
      send: (token, message, conversationId) =>
        market.sendBrandAssistantMessage(token, brandId, {
          message,
          conversation_id: conversationId,
        }),
      usage: market.assistantUsage,
    }),
    [brandId],
  );
  return (
    <AssistantChat
      session={session}
      chatApi={chatApi}
      copy={{
        title: t(locale, "insights.title"),
        subtitle: t(locale, "insights.subtitle"),
        limits: t(locale, "insights.limits"),
        start: t(locale, "insights.start"),
      }}
    />
  );
}

function InsightsContent({ session }: { session: Session }) {
  const brandId = session.me.brand_ids[0];
  if (brandId) return <BrandAssistant session={session} brandId={brandId} />;
  return (
    <PageHeader
      title={t(session.locale, "insights.title")}
      subtitle={t(session.locale, "insights.noBrand")}
    />
  );
}

export default function InsightsPage() {
  return (
    <RoleShell allow={["brand"]}>{(session) => <InsightsContent session={session} />}</RoleShell>
  );
}

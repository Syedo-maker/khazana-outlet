"use client";

import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { t, type Locale } from "@/lib/i18n";
import type { SizeGuide } from "@/lib/market";

/** Each size in the lot with its standard equivalent, from the brand's own chart. */
export function SizeGuideCard({ guide, locale }: { guide: SizeGuide[]; locale: Locale }) {
  if (!guide.some((row) => row.standard)) return null;
  return (
    <Card className="mb-6">
      <CardHeader>
        <CardTitle as="h2">{t(locale, "sizes.guide")}</CardTitle>
      </CardHeader>
      <CardBody>
        <table className="w-full text-sm">
          <tbody>
            {guide.map((row) => (
              <tr key={row.size} className="border-t border-line first:border-t-0">
                <td className="py-1 font-semibold">{row.size}</td>
                <td className="py-1">
                  {row.standard
                    ? t(locale, `sizes.match.${row.match === "close" ? "close" : "approx"}`, {
                        size: row.standard,
                      })
                    : t(locale, "sizes.match.none")}
                </td>
                <td className="py-1 text-ink-soft">{row.measurements}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardBody>
    </Card>
  );
}

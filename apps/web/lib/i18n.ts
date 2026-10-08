/**
 * Language handling.
 *
 * Three languages, because that is what this market actually uses:
 *
 *   en       English
 *   ur       Urdu, right to left
 *   ur_roman Roman Urdu, left to right, Latin script
 *
 * Roman Urdu is the one most teams forget, and it is what a large share of
 * Pakistani users type. It is a separate locale rather than a spelling of
 * Urdu, because it needs Latin script, left to right layout, and its own
 * strings.
 *
 * Direction is derived from the locale here, once, so no component decides it.
 */

export const LOCALES = ["en", "ur", "ur_roman"] as const;
export type Locale = (typeof LOCALES)[number];

export const DEFAULT_LOCALE: Locale = "en";

export function directionFor(locale: Locale): "ltr" | "rtl" {
  return locale === "ur" ? "rtl" : "ltr";
}

export function isLocale(value: string): value is Locale {
  return (LOCALES as readonly string[]).includes(value);
}

type Dictionary = Record<string, string>;

/**
 * Only the strings the Phase 1 shell needs. Phase 3 adds the catalogue and
 * order vocabulary, and the keys stay flat on purpose: a nested structure
 * reads well until a translator has to work through it.
 */
const strings: Record<Locale, Dictionary> = {
  en: {
    "app.name": "Khazana Outlet",
    "app.tagline": "Brand surplus stock, sold properly",
    "nav.skip": "Skip to main content",
    "nav.dashboard": "Dashboard",
    "nav.lots": "Lots",
    "nav.orders": "Orders",
    "nav.signOut": "Sign out",
    "login.title": "Sign in",
    "login.intro": "Enter your mobile number and we will send you a code.",
    "login.phone": "Mobile number",
    "login.phoneHint": "11 digits starting with 03, for example 03001234567",
    "login.sendCode": "Send code",
    "login.code": "Six digit code",
    "login.codeSent": "Code sent to {phone}",
    "login.verify": "Sign in",
    "login.changeNumber": "Use a different number",
    "login.devCode": "Development mode, your code is {code}",
    "state.loading": "Loading",
    "state.errorTitle": "That did not work",
    "state.retry": "Try again",
    "state.emptyTitle": "Nothing here yet",
    "error.network": "Could not reach the server. Check your connection.",
    "error.required": "This is required",
  },
  ur_roman: {
    "app.name": "Khazana Outlet",
    "app.tagline": "Brands ka bacha hua maal, theek tareeqay se",
    "nav.skip": "Main content par jaen",
    "nav.dashboard": "Dashboard",
    "nav.lots": "Lots",
    "nav.orders": "Orders",
    "nav.signOut": "Sign out",
    "login.title": "Sign in karen",
    "login.intro": "Apna mobile number likhen, hum code bhej denge.",
    "login.phone": "Mobile number",
    "login.phoneHint": "11 digit, 03 se shuru, jaise 03001234567",
    "login.sendCode": "Code bhejen",
    "login.code": "Chhe digit ka code",
    "login.codeSent": "Code {phone} par bhej diya",
    "login.verify": "Sign in",
    "login.changeNumber": "Doosra number use karen",
    "login.devCode": "Development mode, aap ka code {code} hai",
    "state.loading": "Load ho raha hai",
    "state.errorTitle": "Yeh kaam nahi kiya",
    "state.retry": "Dobara koshish karen",
    "state.emptyTitle": "Abhi kuch nahi hai",
    "error.network": "Server tak nahi pohancha. Connection check karen.",
    "error.required": "Yeh zaroori hai",
  },
  ur: {
    "app.name": "خزانہ آؤٹ لیٹ",
    "app.tagline": "برانڈز کا بچا ہوا مال، درست طریقے سے",
    "nav.skip": "مرکزی مواد پر جائیں",
    "nav.dashboard": "ڈیش بورڈ",
    "nav.lots": "لاٹس",
    "nav.orders": "آرڈرز",
    "nav.signOut": "سائن آؤٹ",
    "login.title": "سائن ان کریں",
    "login.intro": "اپنا موبائل نمبر لکھیں، ہم کوڈ بھیج دیں گے۔",
    "login.phone": "موبائل نمبر",
    "login.phoneHint": "گیارہ ہندسے، 03 سے شروع، جیسے 03001234567",
    "login.sendCode": "کوڈ بھیجیں",
    "login.code": "چھ ہندسوں کا کوڈ",
    "login.codeSent": "کوڈ {phone} پر بھیج دیا",
    "login.verify": "سائن ان",
    "login.changeNumber": "دوسرا نمبر استعمال کریں",
    "login.devCode": "ڈیولپمنٹ موڈ، آپ کا کوڈ {code} ہے",
    "state.loading": "لوڈ ہو رہا ہے",
    "state.errorTitle": "یہ کام نہیں کیا",
    "state.retry": "دوبارہ کوشش کریں",
    "state.emptyTitle": "ابھی کچھ نہیں ہے",
    "error.network": "سرور تک نہیں پہنچا۔ کنیکشن چیک کریں۔",
    "error.required": "یہ ضروری ہے",
  },
};

/**
 * Look up a string, substituting {placeholders}.
 *
 * A missing key returns the key itself rather than an empty string, so a gap
 * is visible in the interface during development instead of silently
 * rendering nothing.
 */
export function t(
  locale: Locale,
  key: string,
  values: Record<string, string | number> = {},
): string {
  const dictionary = strings[locale] ?? strings[DEFAULT_LOCALE];
  const template = dictionary[key] ?? strings[DEFAULT_LOCALE][key] ?? key;
  return Object.entries(values).reduce(
    (text, [name, value]) => text.replaceAll(`{${name}}`, String(value)),
    template,
  );
}

/** Every key that exists in English, for a completeness check in tests. */
export function allKeys(): string[] {
  return Object.keys(strings[DEFAULT_LOCALE]);
}

/** Which keys a locale is missing. Used by the i18n coverage check. */
export function missingKeys(locale: Locale): string[] {
  const dictionary = strings[locale] ?? {};
  return allKeys().filter((key) => !(key in dictionary));
}

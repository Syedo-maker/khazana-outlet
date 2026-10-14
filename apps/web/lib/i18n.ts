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
 * The shell, the login flow, and the Phase 3 catalogue vocabulary. Orders and
 * payments add their own in weeks 25 to 27.
 *
 * The keys stay flat on purpose: a nested structure reads well until a
 * translator has to work through it. `missingKeys` is the coverage check, so a
 * key added to English and forgotten elsewhere fails a test rather than
 * showing an English string inside an Urdu page.
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
    "lots.title": "Lots",
    "lots.subtitle": "Your stock, from draft to live.",
    "lots.empty": "No lots yet. Create one to start a listing.",
    "lots.code": "Code",
    "lots.pieces": "Pieces",
    "lots.price": "Lot price",
    "lots.discount": "Discount",
    "lots.perPiece": "Per piece",
    "lots.city": "Stock city",
    "lots.open": "Open",
    "lots.manifestShort": "Manifest does not match",
    "status.draft": "Draft",
    "status.pending_approval": "Awaiting approval",
    "status.approved": "Approved",
    "status.live": "Live",
    "status.paused": "Paused",
    "status.sold": "Sold",
    "status.withdrawn": "Withdrawn",
    "status.expired": "Expired",
    "visibility.public": "Public",
    "visibility.private": "Verified buyers only",
    "visibility.unbranded": "Unbranded",
    "grade.A": "Grade A, new with tags",
    "grade.B": "Grade B, no tags, shelf wear",
    "grade.C": "Grade C, itemised defects",
    "manifest.title": "Manifest",
    "manifest.intro": "The size and colour breakdown. It has to add up to the lot total, because that is what buyers check first.",
    "manifest.size": "Size",
    "manifest.colour": "Colour",
    "manifest.pieces": "Pieces",
    "manifest.addLine": "Add a line",
    "manifest.removeLine": "Remove this line",
    "manifest.total": "Manifest total",
    "manifest.lotTotal": "Lot total",
    "manifest.balanced": "Matches the lot total",
    "manifest.short": "{count} pieces short",
    "manifest.over": "{count} pieces too many",
    "manifest.save": "Save the manifest",
    "manifest.saved": "Manifest saved",
    "manifest.import": "Read from a spreadsheet",
    "manifest.importing": "Reading the file",
    "manifest.importReview": "Read {count} rows, {pieces} pieces. Nothing is saved yet, check it first.",
    "manifest.importAccept": "Use these rows",
    "manifest.importDiscard": "Discard",
    "readiness.title": "Before you submit",
    "readiness.ready": "Ready to submit",
    "readiness.blockers": "Needs attention",
    "readiness.warnings": "Worth checking",
    "photos.title": "Photographs",
    "photos.add": "Add a photograph",
    "photos.kind": "View",
    "photos.remove": "Remove",
    "photos.none": "No photographs yet. Three is the minimum.",
    "actions.submit": "Submit for approval",
    "actions.approve": "Approve and publish",
    "actions.reject": "Send back",
    "actions.rejectReason": "What needs fixing?",
    "actions.pause": "Pause",
    "actions.resume": "Resume",
    "actions.withdraw": "Withdraw",
    "action.submitted": "Submitted for approval",
    "action.approved": "Approved",
    "action.rejected": "Sent back",
    "action.withdrawn": "Withdrawn",
    "action.paused": "Paused",
    "action.resumed": "Resumed",
    "trail.title": "Approval history",
    "trail.empty": "Nothing has been submitted yet.",
    "lot.back": "All lots",
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
    "lots.title": "Lots",
    "lots.subtitle": "Aap ka maal, draft se live tak.",
    "lots.empty": "Abhi koi lot nahi. Listing shuru karne ke liye ek banayen.",
    "lots.code": "Code",
    "lots.pieces": "Pieces",
    "lots.price": "Lot ki qeemat",
    "lots.discount": "Discount",
    "lots.perPiece": "Fi piece",
    "lots.city": "Maal ka shehar",
    "lots.open": "Kholen",
    "lots.manifestShort": "Manifest match nahi karta",
    "status.draft": "Draft",
    "status.pending_approval": "Approval ka intezar",
    "status.approved": "Approved",
    "status.live": "Live",
    "status.paused": "Rok diya",
    "status.sold": "Bik gaya",
    "status.withdrawn": "Wapas le liya",
    "status.expired": "Waqt guzar gaya",
    "visibility.public": "Sab ke liye",
    "visibility.private": "Sirf verified kharidar",
    "visibility.unbranded": "Brand ka naam chhupa hua",
    "grade.A": "Grade A, naya tags ke sath",
    "grade.B": "Grade B, tags nahi, halki shelf wear",
    "grade.C": "Grade C, har kharabi likhi hui",
    "manifest.title": "Manifest",
    "manifest.intro": "Size aur rang ki tafseel. Lot ke total ke barabar hona zaroori hai, kharidar pehle yahi dekhte hain.",
    "manifest.size": "Size",
    "manifest.colour": "Rang",
    "manifest.pieces": "Pieces",
    "manifest.addLine": "Line shamil karen",
    "manifest.removeLine": "Yeh line hatayen",
    "manifest.total": "Manifest ka total",
    "manifest.lotTotal": "Lot ka total",
    "manifest.balanced": "Lot ke total se match karta hai",
    "manifest.short": "{count} pieces kam hain",
    "manifest.over": "{count} pieces zyada hain",
    "manifest.save": "Manifest save karen",
    "manifest.saved": "Manifest save ho gaya",
    "manifest.import": "Spreadsheet se parhen",
    "manifest.importing": "File parhi ja rahi hai",
    "manifest.importReview": "{count} rows parhe, {pieces} pieces. Abhi kuch save nahi hua, pehle check karen.",
    "manifest.importAccept": "Yeh rows istemal karen",
    "manifest.importDiscard": "Chhor den",
    "readiness.title": "Submit karne se pehle",
    "readiness.ready": "Submit ke liye tayyar",
    "readiness.blockers": "Tawajjo chahiye",
    "readiness.warnings": "Dekh lena behtar hai",
    "photos.title": "Tasweeren",
    "photos.add": "Tasweer shamil karen",
    "photos.kind": "Rukh",
    "photos.remove": "Hatayen",
    "photos.none": "Abhi koi tasweer nahi. Kam az kam teen chahiye.",
    "actions.submit": "Approval ke liye bhejen",
    "actions.approve": "Approve aur publish karen",
    "actions.reject": "Wapas bhejen",
    "actions.rejectReason": "Kya theek karna hai?",
    "actions.pause": "Rok den",
    "actions.resume": "Dobara chalayen",
    "actions.withdraw": "Wapas le len",
    "action.submitted": "Approval ke liye bheja",
    "action.approved": "Approve kiya",
    "action.rejected": "Wapas bheja",
    "action.withdrawn": "Wapas le liya",
    "action.paused": "Rok diya",
    "action.resumed": "Dobara chalaya",
    "trail.title": "Approval ki tareekh",
    "trail.empty": "Abhi kuch submit nahi hua.",
    "lot.back": "Tamam lots",
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
    "lots.title": "لاٹس",
    "lots.subtitle": "آپ کا مال، ڈرافٹ سے لائیو تک۔",
    "lots.empty": "ابھی کوئی لاٹ نہیں۔ لسٹنگ شروع کرنے کے لیے ایک بنائیں۔",
    "lots.code": "کوڈ",
    "lots.pieces": "پیسز",
    "lots.price": "لاٹ کی قیمت",
    "lots.discount": "ڈسکاؤنٹ",
    "lots.perPiece": "فی پیس",
    "lots.city": "مال کا شہر",
    "lots.open": "کھولیں",
    "lots.manifestShort": "مینیفیسٹ میل نہیں کھاتا",
    "status.draft": "ڈرافٹ",
    "status.pending_approval": "منظوری کا انتظار",
    "status.approved": "منظور شدہ",
    "status.live": "لائیو",
    "status.paused": "روکا ہوا",
    "status.sold": "بک گیا",
    "status.withdrawn": "واپس لے لیا",
    "status.expired": "وقت گزر گیا",
    "visibility.public": "سب کے لیے",
    "visibility.private": "صرف تصدیق شدہ خریدار",
    "visibility.unbranded": "برانڈ کا نام چھپا ہوا",
    "grade.A": "گریڈ اے، نیا ٹیگ کے ساتھ",
    "grade.B": "گریڈ بی، ٹیگ نہیں، ہلکی شیلف ویئر",
    "grade.C": "گریڈ سی، ہر خرابی درج",
    "manifest.title": "مینیفیسٹ",
    "manifest.intro": "سائز اور رنگ کی تفصیل۔ لاٹ کے کل کے برابر ہونا ضروری ہے، خریدار سب سے پہلے یہی دیکھتے ہیں۔",
    "manifest.size": "سائز",
    "manifest.colour": "رنگ",
    "manifest.pieces": "پیسز",
    "manifest.addLine": "لائن شامل کریں",
    "manifest.removeLine": "یہ لائن ہٹائیں",
    "manifest.total": "مینیفیسٹ کا کل",
    "manifest.lotTotal": "لاٹ کا کل",
    "manifest.balanced": "لاٹ کے کل سے میل کھاتا ہے",
    "manifest.short": "{count} پیسز کم ہیں",
    "manifest.over": "{count} پیسز زیادہ ہیں",
    "manifest.save": "مینیفیسٹ محفوظ کریں",
    "manifest.saved": "مینیفیسٹ محفوظ ہو گیا",
    "manifest.import": "اسپریڈ شیٹ سے پڑھیں",
    "manifest.importing": "فائل پڑھی جا رہی ہے",
    "manifest.importReview": "{count} سطریں پڑھی گئیں، {pieces} پیسز۔ ابھی کچھ محفوظ نہیں ہوا، پہلے دیکھ لیں۔",
    "manifest.importAccept": "یہ سطریں استعمال کریں",
    "manifest.importDiscard": "چھوڑ دیں",
    "readiness.title": "بھیجنے سے پہلے",
    "readiness.ready": "بھیجنے کے لیے تیار",
    "readiness.blockers": "توجہ درکار",
    "readiness.warnings": "دیکھ لینا بہتر ہے",
    "photos.title": "تصاویر",
    "photos.add": "تصویر شامل کریں",
    "photos.kind": "رخ",
    "photos.remove": "ہٹائیں",
    "photos.none": "ابھی کوئی تصویر نہیں۔ کم از کم تین درکار ہیں۔",
    "actions.submit": "منظوری کے لیے بھیجیں",
    "actions.approve": "منظور کریں اور شائع کریں",
    "actions.reject": "واپس بھیجیں",
    "actions.rejectReason": "کیا درست کرنا ہے؟",
    "actions.pause": "روک دیں",
    "actions.resume": "دوبارہ چلائیں",
    "actions.withdraw": "واپس لے لیں",
    "action.submitted": "منظوری کے لیے بھیجا",
    "action.approved": "منظور کیا",
    "action.rejected": "واپس بھیجا",
    "action.withdrawn": "واپس لے لیا",
    "action.paused": "روک دیا",
    "action.resumed": "دوبارہ چلایا",
    "trail.title": "منظوری کی تاریخ",
    "trail.empty": "ابھی کچھ نہیں بھیجا گیا۔",
    "lot.back": "تمام لاٹس",
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

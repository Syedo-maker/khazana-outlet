/**
 * The marketplace API: search, cart, orders, payments, shipping and admin.
 *
 * Kept apart from `api.ts`, which holds the transport and the brand catalogue.
 */

import {
  ApiError,
  API_BASE_URL,
  request,
  type ConditionGrade,
  type Lot,
  type LotDetail,
  type LotPhoto,
  type LotStatus,
  type PhotoKind,
  type Visibility,
} from "./api";

export type OrderStatus =
  | "created"
  | "awaiting_payment"
  | "paid"
  | "preparing"
  | "shipped"
  | "delivered"
  | "confirmed"
  | "disputed"
  | "cancelled"
  | "refunded";

export type PaymentMethod = "bank_transfer" | "jazzcash" | "easypaisa" | "card" | "cod";
export type PaymentStatus = "pending" | "held" | "released" | "refunded" | "failed";
export type ShipmentStatus =
  | "pending_pickup"
  | "picked_up"
  | "in_transit"
  | "delivered"
  | "returned"
  | "lost";
export type VerificationStatus = "pending" | "verified" | "rejected" | "suspended";
export type PayoutStatus = "pending" | "scheduled" | "paid" | "failed";
export type DisputeStatus =
  | "open"
  | "under_review"
  | "resolved_buyer"
  | "resolved_seller"
  | "withdrawn";

export type CatalogLot = {
  id: string;
  lot_code: string;
  category_id: string;
  title: string;
  description: string | null;
  season: string | null;
  condition_grade: ConditionGrade;
  total_pieces: number;
  available_pieces: number;
  retail_price_per_piece_pkr: number;
  lot_price_pkr: number;
  min_order_pieces: number;
  stock_city: string;
  status: LotStatus;
  visibility: Visibility;
  price_per_piece_pkr: number;
  discount_percent: number;
};

export type CatalogItem = {
  lot: CatalogLot;
  brand_name: string;
  brand_is_hidden: boolean;
  cover_photo_id: string | null;
  similarity?: number | null;
};

export type Recommendation = CatalogItem & {
  score: number;
  reasons: string[];
  reason_codes: ({ code: string } & Record<string, string>)[];
};

export type ProfitScenario = {
  name: string;
  price_per_piece_pkr: number;
  revenue_pkr: number;
  profit_pkr: number;
  margin_percent: number;
};

export type ProfitEstimate = {
  lot_code: string;
  city: string;
  pieces: number;
  goods_pkr: number;
  shipping_pkr: number | null;
  cost_pkr: number;
  cost_per_piece_pkr: number;
  scenarios: ProfitScenario[];
  break_even_pieces: number | null;
  benchmark: string;
  assumptions: string[];
};

export type LineChoice = { size: string; color: string; pieces: number };

export type ResellKit = {
  order_id: string;
  lot_code: string;
  selling_price_pkr: number;
  caption_en: string;
  caption_ur_roman: string;
  caption_ur: string;
  social_post: string;
  whatsapp_status: string;
  hashtags: string[];
  selling_points: string[];
  price_tags: {
    size: string;
    color: string;
    pieces: number;
    price_en: string;
    price_ur: string;
  }[];
  whatsapp_catalogue: string;
  photo_paths: string[];
};

export type NegotiationMessage = {
  role: "buyer" | "assistant";
  body: string;
  offer_pkr: number | null;
  created_at: string;
};

export type Negotiation = {
  id: string;
  lot_id: string;
  lot_code: string;
  status: "open" | "agreed" | "ordered" | "expired" | "withdrawn";
  pieces: number;
  list_price_pkr: number;
  asking_price_pkr: number;
  agreed_price_pkr: number | null;
  agreed_until: string | null;
  rounds: number;
  order_id: string | null;
  messages: NegotiationMessage[];
};

export type PriceMove = {
  at: string;
  action: string;
  by: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  note: string | null;
};

export type ForecastLot = {
  lot_id: string;
  lot_code: string;
  title: string;
  weekly_pieces: number;
  weeks_to_clear: number | null;
  at_risk: boolean;
  reason: string;
};

export type SeasonEvent = {
  id: string;
  name: string;
  starts_on: string;
  ends_on: string;
  lead_days: number;
  demand_factor: number;
  keywords: string[];
  note: string;
};

export type BrandForecast = {
  computed_at: string | null;
  at_risk: ForecastLot[];
  on_track: ForecastLot[];
  warnings: {
    category: string;
    live_pieces: number;
    weekly_demand: number;
    weeks_of_demand: number | null;
    message: string;
  }[];
  upcoming: SeasonEvent[];
};

export type SizeGuide = {
  size: string;
  standard: string | null;
  match: "close" | "approximate" | "no chart";
  measurements: string;
};

export type SizeRow = {
  audience: string;
  label: string;
  chest_min_cm: number | null;
  chest_max_cm: number | null;
  waist_min_cm: number | null;
  waist_max_cm: number | null;
  hip_min_cm: number | null;
  hip_max_cm: number | null;
  standard: string | null;
};

export type PartnerMatch = {
  partner_id: string;
  name: string;
  kind: "tailor" | "artisan" | "ngo" | "recycler";
  city: string;
  score: number;
  reasons: string[];
};

export type PoolLine = { size: string; color: string; pieces: number };

export type Pool = {
  id: string;
  item: CatalogItem;
  city: string;
  status: "open" | "ordered" | "cancelled" | "expired";
  closes_at: string;
  members: number;
  min_members: number;
  places_left: number;
  pieces_covered: number;
  meets_minimum: boolean;
  shortfall: string[];
  uncovered: PoolLine[];
  mine: {
    requested: PoolLine[];
    allocated: PoolLine[] | null;
    order_id: string | null;
    is_organiser: boolean;
  } | null;
};

export type PoolMembership = {
  lines: PoolLine[];
  delivery_address: string;
  delivery_phone: string;
  payment_method: PaymentMethod;
};

export type MixedLotRequest = {
  budget_pkr: number;
  target_pieces: number;
  category_ids: string[];
  max_brands: number;
  city?: string;
};

export type MixedLotPart = {
  item: CatalogItem;
  pieces: number;
  lines: LineChoice[];
  subtotal_pkr: number;
  shipping_pkr: number;
  total_pkr: number;
  reason: string;
};

export type MixedLot = {
  components: MixedLotPart[];
  pieces: number;
  total_pkr: number;
  brand_count: number;
  budget_pkr: number;
  target_pieces: number;
  notes: string[];
  added_to_cart: boolean;
};

export type CatalogDetail = CatalogItem & {
  photos: { id: string; kind: PhotoKind; sort_order: number }[];
  manifest_lines: LineChoice[];
  available_lines: LineChoice[];
  allows_part_lot: boolean;
  allows_cod: boolean;
  allows_pooling: boolean;
  allows_bargaining: boolean;
  size_guide: SizeGuide[];
  defects: { issue: string; pieces_affected: number; photo_id: string | null }[];
};

export type SearchResult = {
  items: CatalogItem[];
  total: number;
  limit: number;
  offset: number;
  method: string;
  note: string | null;
};

export type SearchFilters = {
  q?: string;
  category_id?: string;
  stock_city?: string;
  grade?: ConditionGrade[];
  max_price_per_piece_pkr?: number;
  min_discount_percent?: number;
  sort?: "newest" | "price_low" | "price_high" | "discount" | "pieces";
};

export type Category = {
  id: string;
  parent_id: string | null;
  name: string;
  slug: string;
  requires_expiry: boolean;
};

export type SavedSearch = {
  id: string;
  name: string;
  filters: SearchFilters;
  new_matches: number;
};

export type CartItem = {
  lot_id: string;
  lot_code: string | null;
  title: string | null;
  seller_name: string | null;
  whole_lot: boolean;
  lines: LineChoice[];
  pieces: number | null;
  subtotal_pkr: number | null;
  shipping_pkr: number | null;
  total_pkr: number | null;
  problem: string | null;
};

export type Cart = { items: CartItem[]; delivery_city: string | null; total_pkr: number };

export type DeliveryDetails = {
  delivery_city: string;
  delivery_address: string;
  delivery_phone: string;
  payment_method: PaymentMethod;
};

export type Order = {
  id: string;
  order_code: string;
  lot_id: string;
  lot_code: string;
  lot_title: string;
  seller_name: string;
  status: OrderStatus;
  payment_method: PaymentMethod;
  pieces: number;
  unit_price_pkr: number;
  subtotal_pkr: number;
  shipping_pkr: number;
  total_pkr: number;
  delivery_city: string;
  created_at: string;
  delivered_at: string | null;
  dispute_window_ends_at: string | null;
  confirmed_at: string | null;
  cancellation_reason: string | null;
  lines: (LineChoice & { unit_price_pkr: number })[];
  delivery_address: string | null;
  delivery_phone: string | null;
  commission_percent: number | null;
  commission_pkr: number | null;
  brand_payout_pkr: number | null;
  buyer_business_name: string | null;
};

export type OrderDispute = {
  id: string;
  reason: string;
  detail: string | null;
  status: DisputeStatus;
  resolution: string | null;
  refund_pkr: number | null;
  created_at: string;
};

export type OrderDetail = Order & {
  events: {
    from_status: OrderStatus | null;
    to_status: OrderStatus;
    actor_role: string;
    note: string | null;
    created_at: string;
  }[];
  disputes: OrderDispute[];
  returns: { id: string; pieces: number; reason: string; created_at: string }[];
};

export type PaymentState = {
  id: string;
  method: PaymentMethod;
  status: PaymentStatus;
  amount_pkr: number;
  refunded_pkr: number;
  reference: string | null;
  failure_reason: string | null;
  action: "sandbox_wallet" | "bank_transfer" | "cash_on_delivery" | null;
  instructions: string | null;
};

export type Shipment = {
  id: string;
  courier: string;
  tracking_number: string | null;
  status: ShipmentStatus;
  cartons: number | null;
  weight_kg: number | null;
  cost_pkr: number | null;
  pickup_scheduled_for: string | null;
  events: {
    status: ShipmentStatus;
    location: string | null;
    note: string | null;
    created_at: string;
  }[];
};

export type ResellerProfile = {
  id: string;
  business_name: string;
  city: string;
  ntn: string | null;
  shop_address: string | null;
  monthly_purchase_pkr: number | null;
  status: VerificationStatus;
  review_note: string | null;
};

export type BrandSummary = {
  id: string;
  name: string;
  slug: string;
  city: string;
  status: VerificationStatus;
  legal_name: string | null;
  ntn: string | null;
  unbranded_label: string | null;
  review_note: string | null;
};

export type BrandPolicy = {
  commission_percent: number;
  payout_terms_days: number;
  dispute_window_days: number;
  min_lot_value_pkr: number;
  default_visibility: Visibility;
  allow_cod: boolean;
  allow_part_lot_orders: boolean;
  allow_pooled_orders: boolean;
  allow_bargaining: boolean;
  bargain_floor_percent: number | null;
  bargain_step_percent: number;
  allow_auto_markdown: boolean;
  markdown_step_percent: number;
  markdown_interval_days: number;
  markdown_floor_percent: number | null;
  min_discount_percent?: number;
  max_discount_percent?: number;
};

export type BrandDashboard = {
  brand: BrandSummary;
  policy: BrandPolicy;
  documents_supplied: string[];
  documents_missing: string[];
  can_request_verification: boolean;
  is_verified: boolean;
  lots_by_status: Record<string, number>;
  live_lots: number;
  orders_this_month: number;
  awaiting_payout_pkr: number;
};

export type Payout = {
  id: string;
  order_id: string;
  brand_id: string;
  amount_pkr: number;
  status: PayoutStatus;
  scheduled_for: string | null;
  paid_at: string | null;
  reference: string | null;
  run_id: string | null;
};

export type NewLot = {
  brand_id: string;
  title: string;
  category_id: string;
  condition_grade: ConditionGrade;
  total_pieces: number;
  retail_price_per_piece_pkr: number;
  lot_price_pkr: number;
  min_order_pieces: number;
  stock_city: string;
  description?: string;
  season?: string;
};

export type Region = { x: number; y: number; width: number; height: number };

function queryString(values: Record<string, unknown>): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) value.forEach((item) => query.append(key, String(item)));
    else query.set(key, String(value));
  }
  const text = query.toString();
  return text ? `?${text}` : "";
}

/** A protected file, read with the bearer token an image tag cannot send. */
export type ChatRole = "buyer" | "assistant";

export type ChatMessage = {
  id: string;
  role: ChatRole;
  body: string;
  language: string | null;
  lot_codes: string[];
  grounded: boolean | null;
  declined: boolean | null;
  created_at: string;
};

export type Conversation = {
  id: string;
  channel: "web" | "whatsapp";
  title: string;
  last_message_at: string | null;
};

export type ConversationDetail = Conversation & { messages: ChatMessage[] };

export type AssistantUsage = { limit: number; used: number; remaining: number };

export type ChatExchange = {
  conversation: Conversation;
  buyer_message: ChatMessage;
  reply: ChatMessage;
  usage: AssistantUsage;
};

export async function fetchFile(path: string, token: string, signal?: AbortSignal): Promise<Blob> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      headers: { Authorization: `Bearer ${token}` },
      signal,
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    throw new ApiError(0, "network", "Could not reach the server.");
  }
  if (!response.ok) throw new ApiError(response.status, "file", "That file is not available.");
  return response.blob();
}

export const market = {
  conversations: (token: string) =>
    request<Conversation[]>("/assistant/conversations", { token }),
  conversation: (token: string, id: string) =>
    request<ConversationDetail>(`/assistant/conversations/${id}`, { token }),
  assistantUsage: (token: string) => request<AssistantUsage>("/assistant/usage", { token }),
  sendAssistantMessage: (
    token: string,
    body: { message: string; conversation_id?: string; city?: string },
  ) => request<ChatExchange>("/assistant/messages", { method: "POST", token, body }),
  brandConversations: (token: string, brandId: string) =>
    request<Conversation[]>(`/brands/${brandId}/assistant/conversations`, { token }),
  brandConversation: (token: string, brandId: string, id: string) =>
    request<ConversationDetail>(`/brands/${brandId}/assistant/conversations/${id}`, { token }),
  sendBrandAssistantMessage: (
    token: string,
    brandId: string,
    body: { message: string; conversation_id?: string },
  ) =>
    request<ChatExchange>(`/brands/${brandId}/assistant/messages`, {
      method: "POST",
      token,
      body,
    }),

  categories: (token: string) => request<Category[]>("/catalog/categories", { token }),

  search: (token: string, filters: SearchFilters, offset = 0) =>
    request<SearchResult>(`/catalog/search${queryString({ ...filters, offset, limit: 24 })}`, {
      token,
    }),

  searchByPhoto: (token: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<SearchResult>("/catalog/search/photo", { method: "POST", token, body: form });
  },

  savedSearches: (token: string) => request<SavedSearch[]>("/catalog/saved-searches", { token }),
  saveSearch: (token: string, name: string, filters: SearchFilters) =>
    request<SavedSearch>("/catalog/saved-searches", {
      method: "POST",
      token,
      body: { name, filters },
    }),
  removeSavedSearch: (token: string, id: string) =>
    request<void>(`/catalog/saved-searches/${id}`, { method: "DELETE", token }),
  runSavedSearch: (token: string, id: string) =>
    request<SearchResult>(`/catalog/saved-searches/${id}/results`, { token }),

  startNegotiation: (token: string, body: { lot_id: string; message: string; offer_pkr?: number }) =>
    request<Negotiation>("/negotiations", { method: "POST", token, body }),
  replyNegotiation: (
    token: string,
    id: string,
    body: { message: string; offer_pkr?: number },
  ) => request<Negotiation>(`/negotiations/${id}/messages`, { method: "POST", token, body }),
  acceptNegotiation: (token: string, id: string) =>
    request<Negotiation>(`/negotiations/${id}/accept`, { method: "POST", token }),
  orderNegotiation: (
    token: string,
    id: string,
    body: { delivery_address: string; delivery_phone: string; payment_method: PaymentMethod },
  ) => request<Negotiation>(`/negotiations/${id}/order`, { method: "POST", token, body }),
  setLotAgents: (
    token: string,
    lotId: string,
    body: { bargaining_enabled?: boolean | null; auto_markdown_enabled?: boolean | null },
  ) => request<unknown>(`/lots/${lotId}/agents`, { method: "PATCH", token, body }),
  priceHistory: (token: string, lotId: string) =>
    request<PriceMove[]>(`/lots/${lotId}/price-history`, { token }),
  brandForecast: (token: string, brandId: string) =>
    request<BrandForecast>(`/brands/${brandId}/forecast`, { token }),
  sizeChart: (token: string, brandId: string) =>
    request<SizeRow[]>(`/brands/${brandId}/size-chart`, { token }),
  saveSizeChart: (token: string, brandId: string, rows: Record<string, unknown>[]) =>
    request<SizeRow[]>(`/brands/${brandId}/size-chart`, { method: "PUT", token, body: rows }),
  partnerMatches: (token: string, lotId: string) =>
    request<PartnerMatch[]>(`/lots/${lotId}/partner-matches`, { token }),
  offerToPartner: (
    token: string,
    lotId: string,
    body: { partner_id: string; route: "donation" | "upcycle_sale"; price_pkr?: number },
  ) => request<unknown>(`/lots/${lotId}/redirections`, { method: "POST", token, body }),
  brandAnalytics: (token: string, brandId: string) =>
    request<BrandAnalytics>(`/brands/${brandId}/analytics`, { token }),
  brandImpact: (token: string, brandId: string) =>
    request<BrandImpact>(`/brands/${brandId}/impact`, { token }),
  pools: (token: string) => request<Pool[]>("/pools", { token }),
  openPool: (token: string, body: PoolMembership & { lot_id: string }) =>
    request<Pool>("/pools", { method: "POST", token, body }),
  joinPool: (token: string, poolId: string, body: PoolMembership) =>
    request<Pool>(`/pools/${poolId}/join`, { method: "POST", token, body }),
  leavePool: (token: string, poolId: string) =>
    request<Pool>(`/pools/${poolId}/leave`, { method: "POST", token }),
  placePool: (token: string, poolId: string) =>
    request<{ order_ids: string[] }>(`/pools/${poolId}/place`, { method: "POST", token }),
  resellKit: (token: string, orderId: string) =>
    request<ResellKit | null>(`/orders/${orderId}/resell-kit`, { token }),
  makeResellKit: (token: string, orderId: string, sellingPrice: number) =>
    request<ResellKit>(`/orders/${orderId}/resell-kit`, {
      method: "POST",
      token,
      body: { selling_price_pkr: sellingPrice },
    }),
  buildMixedLot: (token: string, body: MixedLotRequest) =>
    request<MixedLot>("/catalog/mixed-lots", { method: "POST", token, body }),
  mixedLotToCart: (token: string, body: MixedLotRequest) =>
    request<MixedLot>("/catalog/mixed-lots/cart", { method: "POST", token, body }),
  recommendations: (token: string) =>
    request<Recommendation[]>("/catalog/recommendations", { token }),
  profit: (
    token: string,
    lotId: string,
    params: { city?: string; pieces?: number; selling_price_pkr?: number },
  ) => request<ProfitEstimate>(`/catalog/${lotId}/profit${queryString(params)}`, { token }),

  listing: (token: string, lotId: string) =>
    request<CatalogDetail>(`/catalog/${lotId}`, { token }),

  cart: (token: string, city?: string) =>
    request<Cart>(`/cart${queryString({ delivery_city: city })}`, { token }),
  setCartItem: (token: string, lotId: string, wholeLot: boolean, lines: LineChoice[]) =>
    request<CartItem>(`/cart/items/${lotId}`, {
      method: "PUT",
      token,
      body: { whole_lot: wholeLot, lines },
    }),
  removeCartItem: (token: string, lotId: string) =>
    request<void>(`/cart/items/${lotId}`, { method: "DELETE", token }),
  checkout: (token: string, body: DeliveryDetails) =>
    request<Order[]>("/cart/checkout", { method: "POST", token, body }),

  orders: (token: string, status?: OrderStatus) =>
    request<Order[]>(`/orders${queryString({ status })}`, { token }),
  order: (token: string, id: string) => request<OrderDetail>(`/orders/${id}`, { token }),
  cancelOrder: (token: string, id: string, reason: string) =>
    request<OrderDetail>(`/orders/${id}/cancel`, { method: "POST", token, body: { reason } }),
  prepareOrder: (token: string, id: string) =>
    request<OrderDetail>(`/orders/${id}/prepare`, { method: "POST", token }),
  confirmOrder: (token: string, id: string) =>
    request<OrderDetail>(`/orders/${id}/confirm`, { method: "POST", token }),
  openDispute: (token: string, id: string, reason: string, detail: string) =>
    request<OrderDetail>(`/orders/${id}/disputes`, {
      method: "POST",
      token,
      body: { reason, detail },
    }),
  recordReturn: (token: string, id: string, pieces: number, reason: string) =>
    request<OrderDetail>(`/orders/${id}/returns`, {
      method: "POST",
      token,
      body: { pieces, reason },
    }),

  startPayment: (token: string, id: string) =>
    request<PaymentState>(`/orders/${id}/payment`, { method: "POST", token }),
  completeSandboxPayment: (token: string, id: string, outcome: "succeeded" | "failed") =>
    request<PaymentState>(`/orders/${id}/payment/sandbox-complete`, {
      method: "POST",
      token,
      body: { outcome },
    }),
  submitBankReference: (token: string, id: string, reference: string) =>
    request<PaymentState>(`/orders/${id}/payment/bank-reference`, {
      method: "POST",
      token,
      body: { reference },
    }),

  tracking: (token: string, id: string) =>
    request<Shipment[]>(`/orders/${id}/tracking`, { token }),
  bookShipment: (token: string, id: string) =>
    request<Shipment>(`/orders/${id}/shipments`, { method: "POST", token }),
  schedulePickup: (token: string, shipmentId: string, pickupAt: string) =>
    request<Shipment>(`/shipments/${shipmentId}/pickup`, {
      method: "PUT",
      token,
      body: { pickup_at: pickupAt },
    }),
  advanceShipment: (token: string, shipmentId: string) =>
    request<Shipment>(`/shipments/${shipmentId}/sandbox-advance`, { method: "POST", token }),

  resellerProfile: (token: string) =>
    request<ResellerProfile | null>("/resellers/me", { token }),
  saveResellerProfile: (
    token: string,
    body: Pick<ResellerProfile, "business_name" | "city"> &
      Partial<Pick<ResellerProfile, "ntn" | "shop_address" | "monthly_purchase_pkr">>,
  ) => request<ResellerProfile>("/resellers/me", { method: "PUT", token, body }),

  registerBrand: (token: string, body: { name: string; city: string; ntn?: string }) =>
    request<BrandSummary>("/brands", { method: "POST", token, body }),
  brandDashboard: (token: string, brandId: string) =>
    request<BrandDashboard>(`/brands/${brandId}/dashboard`, { token }),
  uploadDocument: (token: string, brandId: string, docType: string, file: File) => {
    const form = new FormData();
    form.append("doc_type", docType);
    form.append("file", file);
    return request<unknown>(`/brands/${brandId}/documents`, {
      method: "POST",
      token,
      body: form,
    });
  },
  requestVerification: (token: string, brandId: string) =>
    request<BrandSummary>(`/brands/${brandId}/request-verification`, { method: "POST", token }),
  setUnbrandedLabel: (token: string, brandId: string, label: string) =>
    request<BrandSummary>(`/brands/${brandId}/profile`, {
      method: "PATCH",
      token,
      body: { unbranded_label: label },
    }),
  updatePolicy: (token: string, brandId: string, body: Partial<BrandPolicy>) =>
    request<BrandPolicy>(`/brands/${brandId}/policy`, { method: "PATCH", token, body }),
  payouts: (token: string) => request<Payout[]>("/payouts", { token }),

  createLot: (token: string, body: NewLot) =>
    request<LotDetail>("/lots", { method: "POST", token, body }),
  setRegionLock: (token: string, lotId: string, cities: string[]) =>
    request<LotDetail>(`/lots/${lotId}/region-lock`, {
      method: "PUT",
      token,
      body: { cities },
    }),
  scanPhotos: (token: string, lotId: string) =>
    request<LotPhoto[]>(`/lots/${lotId}/photos/protection/scan`, { method: "POST", token }),
  reviewPhoto: (token: string, lotId: string, photoId: string, regions: Region[] | null) =>
    request<LotPhoto>(`/lots/${lotId}/photos/${photoId}/protection`, {
      method: "PUT",
      token,
      body: { regions },
    }),
};

export type AdminOverview = {
  brands_awaiting_review: number;
  resellers_awaiting_review: number;
  listings_awaiting_approval: number;
  live_listings: number;
  open_disputes: number;
  bank_transfers_to_confirm: number;
  held_funds_pkr: number;
  payouts_due_pkr: number;
  ai_spend_today_usd: number;
  orders_by_status: Record<string, number>;
};

export type AdminReseller = {
  id: string;
  full_name: string;
  phone: string;
  business_name: string;
  city: string;
  ntn: string | null;
  shop_address: string | null;
  status: VerificationStatus;
};

export type AdminBrand = {
  brand: BrandSummary;
  policy: BrandPolicy;
  documents: {
    id: string;
    doc_type: string;
    status: VerificationStatus;
    original_filename: string | null;
  }[];
};

export type AdminListing = {
  lot: Lot;
  brand_name: string;
  risk_score: number;
  risk_band: string;
  findings: string[];
};

export type AdminPayment = {
  id: string;
  order_id: string;
  method: PaymentMethod;
  status: PaymentStatus;
  amount_pkr: number;
  provider_reference: string | null;
  failure_reason: string | null;
  created_at: string;
};

export type ReconciliationItem = {
  kind: string;
  payment_id: string;
  order_code: string;
  amount_pkr: number;
  detail: string;
};

export type AdminDispute = {
  id: string;
  order_id: string;
  order_code: string;
  total_pkr: number;
  reason: string;
  detail: string | null;
  status: DisputeStatus;
  resolution: string | null;
  refund_pkr: number | null;
  created_at: string;
};

export type PayoutRun = {
  id: string;
  status: PayoutStatus;
  payout_count: number;
  total_pkr: number;
  reference: string | null;
  paid_at: string | null;
  created_at: string;
};

export type ShippingRate = {
  id: string;
  origin_city: string | null;
  destination_city: string | null;
  base_pkr: number;
  per_kg_pkr: number;
  default_piece_grams: number;
  is_active: boolean;
};

export type Courier = {
  id: string;
  code: string;
  name: string;
  is_active: boolean;
  is_default: boolean;
  rates: ShippingRate[];
};

export type AuditEntry = {
  id: string;
  actor_role: string | null;
  actor_kind: string;
  action: string;
  entity_type: string;
  entity_id: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  note: string | null;
  created_at: string;
};

export type BrandAnalytics = {
  days: number;
  orders: number;
  pieces: number;
  goods_pkr: number;
  payout_pkr: number;
  average_price_per_piece_pkr: number;
  average_discount_percent: number;
  by_city: { city: string; pieces: number }[];
  by_category: { category: string; pieces: number }[];
  by_month: { month: string; pieces: number; goods_pkr: number }[];
  lots_by_status: Record<string, number>;
};

type ImpactTotals = { pieces: number; kg: number; water_litres: number; co2_kg: number };

export type BrandImpact = {
  days: number;
  sold: ImpactTotals;
  second_life: ImpactTotals;
  factors: { keyword: string; kg_per_piece: number; source: string }[];
  assumption: string;
};

export type PlatformReport = {
  days: number;
  gmv_pkr: number;
  orders: number;
  commission_pkr: number;
  active_buyers: number;
  new_accounts: number;
  brands: number;
  live_lots: number;
  change_percent: Record<"gmv" | "orders" | "active_buyers" | "new_accounts", number | null>;
};

export type AiCosts = {
  days: number;
  total_usd: string;
  features: {
    feature: string;
    calls: number;
    cost_usd: string;
    average_usd: string;
    input_tokens: number;
    output_tokens: number;
  }[];
  listings: number;
  orders: number;
  cost_per_listing_usd: string | null;
  cost_per_order_usd: string | null;
  listing_features: string[];
  order_features: string[];
};

export type ReviewCase = {
  id: string;
  subject_type: "account" | "listing" | "order";
  subject_id: string;
  subject_label: string;
  subject_link: string | null;
  score: number;
  signals: { code: string; weight: number; detail: string }[];
  status: "open" | "cleared" | "actioned";
  decision_note: string | null;
  decided_at: string | null;
  scored_at: string;
};

export const adminApi = {
  aiCosts: (token: string) => request<AiCosts>("/admin/ai-costs", { token }),
  analytics: (token: string) => request<PlatformReport>("/admin/analytics", { token }),
  reviewCases: (token: string) => request<ReviewCase[]>("/admin/review-cases", { token }),
  decideCase: (
    token: string,
    id: string,
    body: { outcome: "cleared" | "actioned"; action: string; note: string },
  ) =>
    request<ReviewCase>(`/admin/review-cases/${id}/decision`, { method: "POST", token, body }),
  runRisk: (token: string) =>
    request<{ open_cases: number }>("/admin/jobs/risk", { method: "POST", token }),
  overview: (token: string) => request<AdminOverview>("/admin/overview", { token }),
  resellers: (token: string) => request<AdminReseller[]>("/admin/resellers", { token }),
  reviewReseller: (token: string, id: string, approve: boolean, note: string) =>
    request<AdminReseller>(`/admin/resellers/${id}/review`, {
      method: "POST",
      token,
      body: { approve, note: note || null },
    }),
  brands: (token: string, status?: VerificationStatus) =>
    request<AdminBrand[]>(`/admin/brands${queryString({ status })}`, { token }),
  reviewBrand: (token: string, id: string, approve: boolean, note: string) =>
    request<BrandSummary>(`/brands/${id}/review`, {
      method: "POST",
      token,
      body: { approve, note: note || null },
    }),
  updateTerms: (
    token: string,
    id: string,
    body: { commission_percent?: number; payout_terms_days?: number },
  ) => request<AdminBrand>(`/admin/brands/${id}/terms`, { method: "PATCH", token, body }),
  listings: (token: string, status?: LotStatus, search?: string) =>
    request<AdminListing[]>(`/admin/listings${queryString({ status, search })}`, { token }),
  takeDown: (token: string, id: string, note: string, withdraw: boolean) =>
    request<Lot>(`/admin/listings/${id}/take-down`, {
      method: "POST",
      token,
      body: { note, withdraw },
    }),
  payments: (token: string, status?: PaymentStatus, method?: PaymentMethod) =>
    request<AdminPayment[]>(`/admin/payments${queryString({ status, method })}`, { token }),
  confirmTransfer: (token: string, id: string) =>
    request<AdminPayment>(`/admin/payments/${id}/confirm-transfer`, { method: "POST", token }),
  reconciliation: (token: string) =>
    request<ReconciliationItem[]>("/admin/reconciliation", { token }),
  refund: (token: string, orderId: string, note: string) =>
    request<void>(`/admin/orders/${orderId}/refund`, { method: "POST", token, body: { note } }),
  closeDisputeWindows: (token: string) =>
    request<{ closed: number }>("/admin/jobs/close-dispute-windows", { method: "POST", token }),
  disputes: (token: string) => request<AdminDispute[]>("/admin/disputes", { token }),
  startDisputeReview: (token: string, id: string) =>
    request<AdminDispute>(`/admin/disputes/${id}/review`, { method: "POST", token }),
  resolveDispute: (token: string, id: string, resolution: string, refund: number) =>
    request<AdminDispute>(`/admin/disputes/${id}/resolve`, {
      method: "POST",
      token,
      body: { resolution, refund_pkr: refund },
    }),
  payouts: (token: string) => request<Payout[]>("/admin/payouts", { token }),
  payoutRuns: (token: string) => request<PayoutRun[]>("/admin/payout-runs", { token }),
  createPayoutRun: (token: string) =>
    request<PayoutRun>("/admin/payout-runs", { method: "POST", token, body: {} }),
  markRunPaid: (token: string, id: string, reference: string) =>
    request<PayoutRun>(`/admin/payout-runs/${id}/paid`, {
      method: "POST",
      token,
      body: { reference },
    }),
  couriers: (token: string) => request<Courier[]>("/admin/couriers", { token }),
  addRate: (
    token: string,
    courierId: string,
    body: {
      origin_city: string | null;
      destination_city: string | null;
      base_pkr: number;
      per_kg_pkr: number;
    },
  ) =>
    request<ShippingRate>(`/admin/couriers/${courierId}/rates`, {
      method: "POST",
      token,
      body,
    }),
  updateRate: (token: string, id: string, body: Partial<ShippingRate>) =>
    request<ShippingRate>(`/admin/shipping-rates/${id}`, { method: "PATCH", token, body }),
  audit: (token: string, action?: string, offset = 0) =>
    request<AuditEntry[]>(`/admin/audit${queryString({ action, offset, limit: 50 })}`, { token }),
};

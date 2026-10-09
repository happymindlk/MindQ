import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Building2, Mail, Palette, Phone, Save, Upload } from 'lucide-react';
import Button from '../../components/ui/Button';
import Input from '../../components/ui/Input';
import PageHeader from '../../components/ui/PageHeader';
import { adminApi } from '../../lib/adminApi';

const DEFAULT_BRAND = '#7C3AED';
const PREVIEW_CANVAS = '#0A0A0A';
const PREVIEW_SURFACE = '#0F172A';
const PREVIEW_RAISED = '#111827';
const PREVIEW_BORDER = '#1E293B';
const PREVIEW_FG = '#E8EDF5';
const PREVIEW_MUTED = '#9AA8BC';

/**
 * Expand a 3- or 6-digit hex color to `#RRGGBB`, or return null if invalid.
 *
 * @param {string} value
 * @returns {string | null}
 */
function parseHexColor(value) {
  const raw = (value || '').trim();
  if (/^#([0-9A-Fa-f]{3})$/.test(raw)) {
    const [, h] = raw.match(/^#([0-9A-Fa-f]{3})$/);
    return `#${h[0]}${h[0]}${h[1]}${h[1]}${h[2]}${h[2]}`.toUpperCase();
  }
  if (/^#([0-9A-Fa-f]{6})$/.test(raw)) {
    return raw.toUpperCase();
  }
  return null;
}

/**
 * Convert `#RRGGBB` to an `{ r, g, b }` triple.
 *
 * @param {string} hex
 * @returns {{ r: number, g: number, b: number }}
 */
function hexToRgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 };
}

/**
 * @param {string} hex
 * @param {number} alpha
 * @returns {string}
 */
function withAlpha(hex, alpha) {
  const { r, g, b } = hexToRgb(hex);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

/**
 * Relative luminance of a `#RRGGBB` color, 0–1.
 *
 * @param {string} hex
 * @returns {number}
 */
function luminance(hex) {
  const { r, g, b } = hexToRgb(hex);
  return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
}

/**
 * Pick black or near-white label color so CTA text stays readable on any brand fill.
 *
 * @param {string} hex
 * @returns {string}
 */
function onBrandForeground(hex) {
  return luminance(hex) > 0.55 ? PREVIEW_CANVAS : '#F5F3FF';
}

/**
 * Lighten a dark brand hex so badge/icon text stays readable on the preview canvas.
 *
 * @param {string} hex
 * @returns {string}
 */
function brandOnDark(hex) {
  if (luminance(hex) >= 0.42) return hex;
  const { r, g, b } = hexToRgb(hex);
  const lift = 0.42;
  const toHex = (n) => Math.round(n + (255 - n) * lift).toString(16).padStart(2, '0');
  return `#${toHex(r)}${toHex(g)}${toHex(b)}`.toUpperCase();
}

/**
 * Derive a two-letter mark from the tenant name.
 *
 * @param {string | null | undefined} name
 * @returns {string}
 */
function companyInitials(name) {
  const parts = (name || '').trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return 'CO';
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
}

function CandidatePortalPreview({
  companyName,
  logoUrl,
  brandColor,
  contactEmail,
  contactPhone,
}) {
  const [logoFailed, setLogoFailed] = useState(false);

  useEffect(() => {
    setLogoFailed(false);
  }, [logoUrl]);

  const initials = companyInitials(companyName);
  const showLogo = Boolean(logoUrl) && !logoFailed;
  const ctaFg = onBrandForeground(brandColor);
  const accentText = brandOnDark(brandColor);
  const displayName = companyName || 'Your company';
  const emailLabel = contactEmail?.trim() || 'Add a contact email';
  const phoneLabel = contactPhone?.trim() || 'Add a contact number';

  return (
    <aside
      aria-label="Candidate portal preview"
      className="rounded-lg overflow-hidden lg:sticky lg:top-16"
      style={{
        backgroundColor: PREVIEW_CANVAS,
        border: `1px solid ${withAlpha(brandColor, 0.45)}`,
      }}
    >
      <div
        className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1.5 min-h-12 px-3 py-2"
        style={{
          backgroundColor: PREVIEW_SURFACE,
          borderBottom: `1px solid ${withAlpha(brandColor, 0.35)}`,
        }}
      >
        <div className="flex items-center gap-2 min-w-0 flex-1">
          {showLogo ? (
            <img
              src={logoUrl}
              alt=""
              onError={() => setLogoFailed(true)}
              className="h-7 w-auto max-w-[7.5rem] object-contain rounded-md shrink-0"
              style={{
                backgroundColor: PREVIEW_RAISED,
                border: `1px solid ${withAlpha(brandColor, 0.3)}`,
                padding: 2,
              }}
            />
          ) : (
            <div
              className="h-7 w-7 rounded-md flex items-center justify-center shrink-0 font-semibold text-[10px] tabular-data"
              style={{
                backgroundColor: withAlpha(brandColor, 0.18),
                border: `1px solid ${withAlpha(brandColor, 0.4)}`,
                color: accentText,
              }}
              aria-hidden="true"
            >
              {initials}
            </div>
          )}
          <span className="text-sm font-semibold truncate" style={{ color: PREVIEW_FG }}>
            {displayName}
          </span>
        </div>
        <span
          className="shrink-0 inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium whitespace-nowrap"
          style={{
            backgroundColor: withAlpha(brandColor, 0.16),
            border: `1px solid ${withAlpha(brandColor, 0.4)}`,
            color: accentText,
          }}
        >
          Candidate Portal Preview
        </span>
      </div>

      <div className="px-4 py-4 space-y-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-sm font-semibold" style={{ color: PREVIEW_FG }}>
              Cognitive Reasoning
            </p>
            <p className="text-xs mt-1 tabular-data" style={{ color: PREVIEW_MUTED }}>
              12 min · 24 items
            </p>
          </div>
          <span
            className="shrink-0 inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-medium"
            style={{
              backgroundColor: withAlpha(brandColor, 0.16),
              border: `1px solid ${withAlpha(brandColor, 0.35)}`,
              color: accentText,
            }}
          >
            Timed
          </span>
        </div>

        <div
          className="h-1.5 rounded-full overflow-hidden"
          style={{ backgroundColor: PREVIEW_RAISED, border: `1px solid ${PREVIEW_BORDER}` }}
        >
          <div
            className="h-full w-1/3 rounded-full"
            style={{ backgroundColor: brandColor }}
          />
        </div>

        <button
          type="button"
          tabIndex={-1}
          aria-hidden="true"
          className="h-9 w-full rounded-md text-sm font-medium pointer-events-none"
          style={{ backgroundColor: brandColor, color: ctaFg }}
        >
          Begin Assessment
        </button>
      </div>

      <div
        className="px-4 py-2.5 flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-4"
        style={{
          backgroundColor: PREVIEW_RAISED,
          borderTop: `1px solid ${withAlpha(brandColor, 0.28)}`,
        }}
      >
        <p
          className="flex items-center gap-1.5 text-xs min-w-0 sm:flex-1"
          style={{ color: contactEmail?.trim() ? PREVIEW_FG : PREVIEW_MUTED }}
        >
          <Mail className="w-3.5 h-3.5 shrink-0" style={{ color: accentText }} aria-hidden="true" />
          <span className="truncate">{emailLabel}</span>
        </p>
        <p
          className="flex items-center gap-1.5 text-xs min-w-0 sm:flex-1"
          style={{ color: contactPhone?.trim() ? PREVIEW_FG : PREVIEW_MUTED }}
        >
          <Phone className="w-3.5 h-3.5 shrink-0" style={{ color: accentText }} aria-hidden="true" />
          <span className="truncate">{phoneLabel}</span>
        </p>
      </div>
    </aside>
  );
}

export default function Corporates() {
  const fileInputRef = useRef(null);
  const lastValidColorRef = useRef(DEFAULT_BRAND);
  const [corporate, setCorporate] = useState(null);
  const [logoUrl, setLogoUrl] = useState('');
  const [primaryColor, setPrimaryColor] = useState(DEFAULT_BRAND);
  const [contactEmail, setContactEmail] = useState('');
  const [contactPhone, setContactPhone] = useState('');
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isUploading, setIsUploading] = useState(false);

  const parsedColor = parseHexColor(primaryColor);
  const brandColor = parsedColor || lastValidColorRef.current;
  const colorInvalid = Boolean(primaryColor.trim()) && !parsedColor;

  useEffect(() => {
    if (parsedColor) {
      lastValidColorRef.current = parsedColor;
    }
  }, [parsedColor]);

  useEffect(() => {
    adminApi
      .getCorporate()
      .then((data) => {
        setCorporate(data);
        setLogoUrl(data?.logo_url || '');
        const nextColor = parseHexColor(data?.primary_color) || DEFAULT_BRAND;
        lastValidColorRef.current = nextColor;
        setPrimaryColor(data?.primary_color || DEFAULT_BRAND);
        setContactEmail(data?.contact_email || '');
        setContactPhone(data?.contact_phone || '');
      })
      .catch((err) => setError(err.message));
  }, []);

  const handleLogoUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file || !corporate?.id) return;
    setIsUploading(true);
    setError(null);
    try {
      const publicUrl = await adminApi.uploadCorporateLogo(corporate.id, file);
      setLogoUrl(publicUrl);
    } catch (err) {
      setError(err.message || 'Logo upload failed');
    } finally {
      setIsUploading(false);
      e.target.value = '';
    }
  };

  const handleSave = async () => {
    if (!corporate?.id) return;
    setIsSaving(true);
    setError(null);
    setSaved(false);
    try {
      const updated = await adminApi.updateCorporate(corporate.id, {
        logo_url: logoUrl || null,
        primary_color: primaryColor || null,
        contact_email: contactEmail || null,
        contact_phone: contactPhone || null,
      });
      setCorporate(updated);
      setSaved(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setIsSaving(false);
    }
  };

  const previewProps = useMemo(
    () => ({
      companyName: corporate?.name,
      logoUrl,
      brandColor,
      contactEmail,
      contactPhone,
    }),
    [corporate?.name, logoUrl, brandColor, contactEmail, contactPhone],
  );

  return (
    <div className="max-w-6xl space-y-6">
      <PageHeader
        title="Corporates"
        description="B2B tenant profile, contact details, and white-label branding for the candidate portal."
      />

      {error && (
        <p className="text-sm text-danger" role="alert">
          {error}
        </p>
      )}
      {saved && (
        <p className="text-sm text-success" role="status">
          Branding saved.
        </p>
      )}

      <section className="rounded-lg bg-surface border border-border">
        <div className="flex items-start gap-3 px-4 py-4">
          <div className="p-2 rounded-md bg-primary/10 text-primary-text">
            <Building2 className="w-4 h-4" />
          </div>
          <div className="flex-1 space-y-4 min-w-0">
            <div>
              <p className="text-xs font-medium text-muted">Organization</p>
              <p className="text-sm font-semibold text-foreground mt-1">
                {corporate?.name || '—'}
              </p>
            </div>
            <div className="h-px bg-border" />
            <div>
              <p className="text-xs font-medium text-muted">Slug</p>
              <p className="font-mono text-sm text-primary-text mt-1 tabular-data">
                {corporate?.slug || '—'}
              </p>
            </div>
            <p className="flex items-center gap-2 text-xs text-muted">
              <Mail className="w-3.5 h-3.5 shrink-0" />
              Tenant isolation is enforced by RLS via your signed-in corporate_id.
            </p>
          </div>
        </div>
      </section>

      <section>
        <div className="flex items-center gap-2 mb-1.5">
          <Palette className="w-4 h-4 text-muted" />
          <h2 className="text-sm font-semibold text-foreground">White-label branding</h2>
        </div>
        <p className="text-xs text-muted mb-4 max-w-2xl leading-relaxed">
          Logo, color, and support contacts appear on the candidate test screen. The preview
          updates as you type — save when you are ready to publish.
        </p>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start">
          <div className="rounded-lg bg-surface border border-border px-4 py-4 space-y-4">
            <div>
              <label className="block text-xs font-medium text-muted mb-1.5">
                Corporate logo
              </label>
              <div className="flex flex-col sm:flex-row sm:items-center gap-3">
                {logoUrl ? (
                  <img
                    src={logoUrl}
                    alt="Corporate logo"
                    className="h-12 w-auto max-w-[160px] object-contain rounded-md bg-canvas p-1 border border-border"
                  />
                ) : (
                  <div className="h-12 w-24 rounded-md border border-dashed border-border bg-canvas flex items-center justify-center text-[10px] font-semibold tabular-data text-muted">
                    {companyInitials(corporate?.name)}
                  </div>
                )}
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/png,image/jpeg,image/webp,image/svg+xml"
                  className="sr-only"
                  onChange={handleLogoUpload}
                  disabled={!corporate?.id || isUploading}
                />
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  isLoading={isUploading}
                  disabled={!corporate?.id}
                  onClick={() => fileInputRef.current?.click()}
                  className="shrink-0"
                >
                  <Upload className="w-3.5 h-3.5" />
                  Upload logo
                </Button>
                <div className="flex-1 min-w-0">
                  <Input
                    placeholder="https://cdn.example.com/logo.png"
                    value={logoUrl}
                    onChange={(e) => setLogoUrl(e.target.value)}
                    aria-label="Logo URL"
                  />
                </div>
              </div>
              <p className="mt-2 text-xs text-muted">
                Upload stores the file on Cloudflare R2, or paste an existing public URL.
              </p>
            </div>

            <div className="h-px bg-border" />

            <div>
              <label htmlFor="brand-primary-color" className="block text-xs font-medium text-muted mb-1.5">
                Primary color
              </label>
              <div className="flex items-start gap-2">
                <input
                  id="brand-color-picker"
                  type="color"
                  value={brandColor}
                  onChange={(e) => setPrimaryColor(e.target.value.toUpperCase())}
                  className="h-9 w-9 shrink-0 cursor-pointer rounded-md border border-border bg-canvas p-0.5"
                  aria-label="Pick primary color"
                />
                <div className="flex-1 min-w-0">
                  <Input
                    id="brand-primary-color"
                    placeholder={DEFAULT_BRAND}
                    value={primaryColor}
                    onChange={(e) => setPrimaryColor(e.target.value)}
                    className="tabular-data"
                    error={colorInvalid ? 'Use a 3- or 6-digit hex code, e.g. #7C3AED.' : undefined}
                  />
                </div>
              </div>
            </div>

            <Input
              label="Contact email"
              type="email"
              icon={Mail}
              placeholder="hr@example.com"
              value={contactEmail}
              onChange={(e) => setContactEmail(e.target.value)}
            />
            <Input
              label="HR contact number"
              icon={Phone}
              placeholder="+1 555 0100"
              value={contactPhone}
              onChange={(e) => setContactPhone(e.target.value)}
            />

            <div className="flex items-center gap-3 pt-1">
              <Button
                onClick={handleSave}
                isLoading={isSaving}
                disabled={!corporate?.id}
              >
                <Save className="w-3.5 h-3.5" /> Save Branding
              </Button>
            </div>
          </div>

          <CandidatePortalPreview {...previewProps} />
        </div>
      </section>
    </div>
  );
}

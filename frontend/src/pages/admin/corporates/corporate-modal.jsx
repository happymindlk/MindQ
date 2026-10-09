import React, { useEffect, useId, useRef, useState } from 'react';
import { Building2, Info, Mail, X } from 'lucide-react';
import Modal from '../../../components/ui/Modal';
import Input from '../../../components/ui/Input';
import Button from '../../../components/ui/Button';
import { useToast } from '../../../components/ui/useToast';
import CorporateLogo from './corporate-logo';

const ACCEPTED_TYPES = ['image/png', 'image/jpeg', 'image/webp', 'image/svg+xml'];
const MAX_LOGO_BYTES = 2 * 1024 * 1024;
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@.]+$/;

/**
 * @param {File} file
 * @returns {string | null} Error message, or null when the file is acceptable.
 */
function validateLogoFile(file) {
  if (!ACCEPTED_TYPES.includes(file.type)) return 'Use a PNG, JPEG, WebP, or SVG image.';
  if (file.size === 0) return 'That file is empty.';
  if (file.size > MAX_LOGO_BYTES) return 'Logo must be 2 MB or smaller.';
  return null;
}

/**
 * @param {{ name: string, contactEmail: string }} values
 * @returns {{ name?: string, contactEmail?: string }}
 */
function validateFields({ name, contactEmail }) {
  const errors = {};
  if (!name.trim()) errors.name = 'Company name is required.';
  else if (name.trim().length > 255) errors.name = 'Keep the name under 255 characters.';
  if (contactEmail.trim() && !EMAIL_PATTERN.test(contactEmail.trim())) {
    errors.contactEmail = 'Enter a valid email address.';
  }
  return errors;
}

function LogoDropzone({ inputId, previewUrl, fallbackName, error, disabled, onFile, onClear }) {
  const inputRef = useRef(null);
  const [isDragging, setIsDragging] = useState(false);

  const handleFiles = (files) => {
    const file = files?.[0];
    if (file) onFile(file);
  };

  return (
    <div>
      <span className="metric-label mb-1.5 block">Company logo</span>
      <div
        onDragOver={(event) => {
          event.preventDefault();
          if (!disabled) setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setIsDragging(false);
          if (!disabled) handleFiles(event.dataTransfer.files);
        }}
        className={`flex items-center gap-4 rounded-md border border-dashed px-4 py-4 transition-colors duration-150 ${
          isDragging
            ? 'border-blue-600 bg-blue-600/5'
            : error
              ? 'border-danger'
              : 'border-slate-300 dark:border-neutral-700'
        } ${disabled ? 'opacity-50' : ''}`}
      >
        <CorporateLogo name={fallbackName} logoUrl={previewUrl} size="lg" />
        <div className="min-w-0 flex-1">
          <p className="text-sm text-foreground">
            Drag an image here or{' '}
            <button
              type="button"
              disabled={disabled}
              onClick={() => inputRef.current?.click()}
              className="font-medium text-blue-600 dark:text-blue-400 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 rounded-sm disabled:cursor-not-allowed"
            >
              browse
            </button>
          </p>
          <p className="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
            PNG, JPEG, WebP, or SVG up to 2 MB.
          </p>
        </div>
        {onClear && (
          <button
            type="button"
            onClick={onClear}
            disabled={disabled}
            aria-label="Remove selected logo"
            className="p-1.5 rounded-md text-neutral-400 hover:text-foreground hover:bg-slate-100 dark:hover:bg-neutral-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        )}
        <input
          ref={inputRef}
          id={inputId}
          type="file"
          accept={ACCEPTED_TYPES.join(',')}
          className="sr-only"
          disabled={disabled}
          onChange={(event) => {
            handleFiles(event.target.files);
            event.target.value = '';
          }}
        />
      </div>
      {error && <p className="mt-1.5 text-xs text-danger">{error}</p>}
    </div>
  );
}

/**
 * Create / edit dialog for a corporate. Create mode when `corporate` is null.
 *
 * @param {object} props
 * @param {boolean} props.isOpen
 * @param {import('./use-corporates').CorporateRow | null} props.corporate
 * @param {() => void} props.onClose
 * @param {(input: import('./use-corporates').SaveCorporateInput) =>
 *   Promise<import('./use-corporates').SaveCorporateResult>} props.onSave
 */
export default function CorporateModal({ isOpen, corporate, onClose, onSave }) {
  const { toast } = useToast();
  const formId = useId();
  const logoInputId = useId();
  const isEdit = Boolean(corporate);

  const [name, setName] = useState('');
  const [contactEmail, setContactEmail] = useState('');
  const [logoFile, setLogoFile] = useState(null);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [errors, setErrors] = useState({});
  const [submitError, setSubmitError] = useState(null);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    setName(corporate?.name ?? '');
    setContactEmail(corporate?.contact_email ?? '');
    setLogoFile(null);
    setErrors({});
    setSubmitError(null);
  }, [isOpen, corporate]);

  useEffect(() => {
    if (!logoFile) {
      setPreviewUrl(null);
      return undefined;
    }
    const url = URL.createObjectURL(logoFile);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [logoFile]);

  const handleLogoFile = (file) => {
    const message = validateLogoFile(file);
    setErrors((prev) => ({ ...prev, logo: message ?? undefined }));
    if (!message) setLogoFile(file);
  };

  const handleClose = () => {
    if (!isSaving) onClose();
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    const fieldErrors = validateFields({ name, contactEmail });
    setErrors((prev) => ({ logo: prev.logo, ...fieldErrors }));
    if (Object.keys(fieldErrors).length > 0) return;

    setIsSaving(true);
    setSubmitError(null);
    try {
      const { corporate: saved, logoError } = await onSave({
        id: corporate?.id,
        name: name.trim(),
        contactEmail: contactEmail.trim(),
        logoFile,
      });
      if (logoError) {
        toast({
          variant: 'warning',
          title: `${saved.name} saved, but the logo did not upload`,
          description: `${logoError} Open the editor to try again.`,
          duration: 6000,
        });
      } else {
        toast({
          variant: 'success',
          title: isEdit ? 'Corporate updated' : 'Corporate created',
          description: saved.name,
        });
      }
      onClose();
    } catch (err) {
      const message = err.message || 'Something went wrong. Try again.';
      setSubmitError(message);
      toast({ variant: 'error', title: isEdit ? 'Update failed' : 'Create failed', description: message });
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      title={isEdit ? `Edit ${corporate.name}` : 'Create corporate'}
      actions={
        <>
          <Button type="button" variant="secondary" size="sm" onClick={handleClose} disabled={isSaving}>
            Cancel
          </Button>
          <Button type="submit" form={formId} variant="accent" size="sm" isLoading={isSaving}>
            {isEdit ? 'Save changes' : 'Create corporate'}
          </Button>
        </>
      }
    >
      <form id={formId} onSubmit={handleSubmit} noValidate className="space-y-4">
        <Input
          label="Company name"
          icon={Building2}
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Acme Corp"
          error={errors.name}
          disabled={isSaving}
          maxLength={255}
          autoFocus
          required
        />
        <Input
          label="HR email"
          type="email"
          icon={Mail}
          value={contactEmail}
          onChange={(event) => setContactEmail(event.target.value)}
          placeholder="hr@acme.com"
          error={errors.contactEmail}
          disabled={isSaving}
          autoComplete="off"
        />
        <LogoDropzone
          inputId={logoInputId}
          previewUrl={previewUrl ?? corporate?.logo_url ?? null}
          fallbackName={name || corporate?.name}
          error={errors.logo}
          disabled={isSaving}
          onFile={handleLogoFile}
          onClear={logoFile ? () => setLogoFile(null) : null}
        />
        {submitError && (
          <p className="text-xs text-danger" role="alert">
            {submitError}
          </p>
        )}
        <p className="flex items-center gap-1.5 text-xs text-neutral-500 dark:text-neutral-400">
          <Info className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
          Saving the HR email does not send a portal invite.
        </p>
      </form>
    </Modal>
  );
}

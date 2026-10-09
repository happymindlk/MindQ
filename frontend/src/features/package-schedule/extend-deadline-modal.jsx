import React from 'react';
import Modal from '../../components/ui/Modal';
import Button from '../../components/ui/Button';
import Input from '../../components/ui/Input';
import { formatSriLankaDateTime, SRI_LANKA_ZONE_LABEL } from './sri-lanka-time';
import { useExtendDeadline } from './use-extend-deadline';

const QUICK_EXTENSIONS = [1, 3, 7];

/**
 * Ops dialog to move a live package's close_time.
 *
 * @param {object} props
 * @param {boolean} props.isOpen
 * @param {() => void} props.onClose
 * @param {{ id: string, title: string, open_time?: string | null, close_time?: string | null } | null} props.pkg
 * @param {(updated: { id: string, open_time: string | null, close_time: string | null }) => void} props.onSaved
 */
export default function ExtendDeadlineModal({ isOpen, onClose, pkg, onSaved }) {
  const { value, onChange, error, saving, quickExtend, submit, removeDeadline } =
    useExtendDeadline(pkg, onSaved);
  const current = formatSriLankaDateTime(pkg?.close_time);

  return (
    <Modal
      isOpen={isOpen}
      onClose={saving ? undefined : onClose}
      title="Extend deadline"
      actions={
        <>
          {pkg?.close_time && (
            <Button
              variant="ghost"
              size="sm"
              className="mr-auto"
              onClick={removeDeadline}
              disabled={saving}
            >
              Remove deadline
            </Button>
          )}
          <Button variant="secondary" size="sm" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button size="sm" onClick={submit} isLoading={saving}>
            Save deadline
          </Button>
        </>
      }
    >
      <form
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <div>
          <p className="text-sm font-medium text-foreground">{pkg?.title}</p>
          <p className="mt-1 text-xs text-muted">
            Current deadline:{' '}
            <span className="font-medium text-foreground tabular-data">
              {current ? `${current} (${SRI_LANKA_ZONE_LABEL})` : 'None'}
            </span>
          </p>
        </div>

        <Input
          type="datetime-local"
          label="New deadline (IST / GMT+5:30)"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          error={error || undefined}
          disabled={saving}
          required
        />

        <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Quick extend">
          <span className="text-xs text-muted">Quick extend:</span>
          {QUICK_EXTENSIONS.map((days) => (
            <Button
              key={days}
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => quickExtend(days)}
              disabled={saving}
            >
              +{days} {days === 1 ? 'day' : 'days'}
            </Button>
          ))}
        </div>

        <p className="text-xs text-muted">
          Candidates who already started a module can always finish it. Unstarted modules unlock
          again as soon as the new deadline is saved.
        </p>
      </form>
    </Modal>
  );
}

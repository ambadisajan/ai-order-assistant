import React from 'react';

export default function ConfirmModal({ isOpen, title, message, confirmText = 'Confirm', onConfirm, onCancel }) {
  if (!isOpen) return null;

  return (
    <div className="modal-backdrop" onClick={onCancel} role="dialog" aria-modal="true" aria-labelledby="modal-title">
      <div className="modal-card" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-icon-warning">⚠️</div>
          <h3 id="modal-title" className="modal-title">{title}</h3>
        </div>
        <div className="modal-body">
          <p className="modal-message">{message}</p>
        </div>
        <div className="modal-actions">
          <button type="button" className="btn-modal-cancel" onClick={onCancel}>
            Cancel
          </button>
          <button type="button" className="btn-modal-danger" onClick={onConfirm}>
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  );
}

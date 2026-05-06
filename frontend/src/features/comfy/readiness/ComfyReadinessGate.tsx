import { useState } from "react";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import {
  useReadiness,
  useRefreshReadiness,
  type ReadinessCard,
  type ReadinessStatus,
} from "@/api/comfy";
import { ComfyBulkImportModal } from "./ComfyBulkImportModal";
import { ComfyImportModal } from "./ComfyImportModal";
import styles from "./ComfyReadinessGate.module.css";

const STATUS_LABEL: Record<ReadinessStatus, string> = {
  ready: "Ready",
  needs_config: "Needs config",
  not_installed: "Not installed",
};

export function ComfyReadinessGate({
  sessionId,
  onContinue,
}: {
  sessionId: string;
  onContinue?: () => void;
}) {
  const readiness = useReadiness(sessionId);
  const refresh = useRefreshReadiness(sessionId);
  const [importTarget, setImportTarget] = useState<ReadinessCard | null>(null);
  const [bulkOpen, setBulkOpen] = useState(false);
  const ready = readiness.data?.ready === true;
  const needsConfigCards = (readiness.data?.cards ?? []).filter(
    (c) => c.status === "needs_config",
  );

  return (
    <div className={styles.page}>
      {importTarget && (
        <ComfyImportModal
          classType={importTarget.class_type}
          classDisplayName={importTarget.display_name ?? importTarget.class_type}
          open={true}
          onOpenChange={(o) => {
            if (!o) setImportTarget(null);
          }}
          onImported={() => {
            // Re-fetch readiness so the card flips to "ready".
            refresh.mutate();
          }}
        />
      )}
      <ComfyBulkImportModal
        targets={needsConfigCards}
        open={bulkOpen}
        onOpenChange={setBulkOpen}
        onCompleted={() => refresh.mutate()}
      />
      <div className={styles.head}>
        <div className={styles.headBody}>
          <h2 className={styles.title}>Workflow readiness</h2>
          <p className={styles.subtitle}>
            Every distinct node class in this workflow has to be either configured
            in the catalog or marked as not requiring configuration before the
            session can move forward. Nodes still missing from your ComfyUI install
            need to be installed there first; press Refresh after.
          </p>
        </div>
        <Button
          icon={<Icon name="RotateCw" size={12} />}
          onClick={() => refresh.mutate()}
          disabled={refresh.isPending}
        >
          {refresh.isPending ? "Refreshing…" : "Refresh"}
        </Button>
      </div>

      {readiness.isLoading && <div className={styles.empty}>Loading readiness…</div>}

      {readiness.data?.error && (
        <div className={styles.gateBanner} data-tone="error" role="alert">
          <Icon name="AlertCircle" size={14} />
          <span>{readiness.data.error}</span>
        </div>
      )}

      {readiness.data && !readiness.data.error && (
        <div
          className={styles.gateBanner}
          data-tone={ready ? "ready" : undefined}
        >
          <Icon name={ready ? "Check" : "AlertCircle"} size={14} />
          <span>
            {ready
              ? `All ${readiness.data.cards.length} node classes are ready.`
              : `${readiness.data.cards.filter((c) => c.status !== "ready").length} of ${readiness.data.cards.length} node classes still need attention.`}
          </span>
        </div>
      )}

      {readiness.data && readiness.data.cards.length === 0 && !readiness.data.error && (
        <div className={styles.empty}>
          The workflow doesn't reference any node classes — that's unusual. Inspect the saved JSON.
        </div>
      )}

      <div className={styles.cards}>
        {readiness.data?.cards.map((card) => (
          <Card
            key={card.class_type}
            card={card}
            onImport={() => setImportTarget(card)}
          />
        ))}
      </div>

      {(onContinue || needsConfigCards.length > 0) && (
        <div className={styles.foot}>
          {needsConfigCards.length > 0 && (
            <Button
              icon={<Icon name="Sparkles" size={12} />}
              onClick={() => setBulkOpen(true)}
              title="Run the per-node import wizard against every node class still marked needs config."
            >
              Import all ({needsConfigCards.length})
            </Button>
          )}
          {onContinue && (
            <Button
              variant="primary"
              disabled={!ready}
              onClick={onContinue}
              title={
                ready
                  ? "Move on to slot mapping."
                  : "Resolve every node class above before continuing."
              }
              icon={<Icon name="ChevronRight" size={12} />}
            >
              Continue to slot mapping
            </Button>
          )}
        </div>
      )}
    </div>
  );
}


function Card({
  card, onImport,
}: {
  card: ReadinessCard;
  onImport: () => void;
}) {
  return (
    <div className={styles.card} data-status={card.status}>
      <div>
        <div className={styles.cardTitleRow}>
          <span className={styles.cardTitle}>{card.display_name ?? card.class_type}</span>
          <span className={styles.badge} data-status={card.status}>
            {STATUS_LABEL[card.status]}
          </span>
          {card.display_name && card.display_name !== card.class_type && (
            <span className={styles.cardClassType}>{card.class_type}</span>
          )}
        </div>
        <div className={styles.cardMeta}>
          <span>×{card.instance_count}</span>
          {card.pack_name && <span>pack: {card.pack_name}</span>}
          {card.category && <span>category: {card.category}</span>}
          {card.python_module && <span>module: {card.python_module}</span>}
        </div>
        {card.description && (
          <div className={styles.cardDescription}>{card.description}</div>
        )}
        {card.status === "not_installed" && (
          <div className={styles.cardDescription}>
            This class isn't loaded in your ComfyUI right now. Install the pack that
            provides it (or check why it's failing to load), then press Refresh above.
          </div>
        )}
      </div>
      <div className={styles.cardActions}>
        {card.status === "needs_config" && (
          <Button variant="primary" onClick={onImport}>
            Import…
          </Button>
        )}
      </div>
    </div>
  );
}

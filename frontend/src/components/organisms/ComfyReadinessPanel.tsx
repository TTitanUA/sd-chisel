import { useState } from "react";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import {
  useReadiness,
  useRefreshReadiness,
  type ReadinessCard,
  type ReadinessStatus,
} from "@/api/comfy";
import { ComfyImportModal } from "./ComfyImportModal";
import styles from "./ComfyReadinessPanel.module.css";

const STATUS_LABEL: Record<ReadinessStatus, string> = {
  ready: "Ready",
  needs_config: "Needs config",
  not_installed: "Not installed",
};

export function ComfyReadinessPanel({ sessionId }: { sessionId: string }) {
  const readiness = useReadiness(sessionId);
  const refresh = useRefreshReadiness(sessionId);
  const [importTarget, setImportTarget] = useState<ReadinessCard | null>(null);

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
          data-tone={readiness.data.ready ? "ready" : undefined}
        >
          <Icon name={readiness.data.ready ? "Check" : "AlertCircle"} size={14} />
          <span>
            {readiness.data.ready
              ? `All ${readiness.data.cards.length} node classes are ready. (Slot mapping and generation arrive in later phases.)`
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

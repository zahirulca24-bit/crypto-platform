"use client"
import { RemoteCollectionPage } from "@/components/remote-collection"
export default function LearningJournalPage(){return <RemoteCollectionPage title="Learning Journal" subtitle="Unified newest-first Phase-3 lifecycle events from ResearchObservation." endpoint="/v1/research/learning-journal" emptyMessage="No research lifecycle events are available." columns={[{key:"event_type",label:"Event"},{key:"symbol",label:"Symbol"},{key:"strategy_name",label:"Strategy"},{key:"source",label:"Source"},{key:"created_at",label:"Created"},{key:"context",label:"Context"}]}/>}

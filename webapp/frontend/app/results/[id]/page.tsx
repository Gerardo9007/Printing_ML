import ResultView from "@/components/ResultView";

export default function ResultsPage({ params }: { params: { id: string } }) {
  return <ResultView id={params.id} />;
}

import ResultViewDieBlade from "@/components/dieblade/ResultViewDieBlade";

export default function DieBladeResultsPage({ params }: { params: { id: string } }) {
  return <ResultViewDieBlade id={params.id} />;
}

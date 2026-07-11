import UploadFormDieBlade from "@/components/dieblade/UploadFormDieBlade";

export default function DieBladeUploadPage() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-8">
      <header className="mb-8">
        <h1 className="text-2xl font-bold text-ink-primary md:text-3xl">
          목형 칼날검사 뷰어
        </h1>
        <p className="mt-1 text-sm text-ink-secondary">
          촬영된 목형 이미지를 업로드하면 기준 도면과 정합 후 휨·끊김·마모·위치오차를
          검출합니다.
        </p>
      </header>
      <UploadFormDieBlade />
    </main>
  );
}

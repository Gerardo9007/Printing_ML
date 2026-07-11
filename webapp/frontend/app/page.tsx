import UploadForm from "@/components/UploadForm";

export default function UploadPage() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-8">
      <header className="mb-8">
        <h1 className="text-2xl font-bold text-ink-primary md:text-3xl">
          인쇄판 문안검사 뷰어
        </h1>
        <p className="mt-1 text-sm text-ink-secondary">
          결함 이미지를 업로드하면 참조 이미지와 정합 후 차이 영역을 검출합니다.
        </p>
      </header>
      <UploadForm />
    </main>
  );
}

import React from 'react';
import { useNavigate } from 'react-router-dom';
import { FileQuestion, ArrowLeft } from 'lucide-react';
import { Layout } from '../components/layout/Layout';

export const NotFound: React.FC = () => {
  const navigate = useNavigate();

  return (
    <Layout title="Page Not Found">
      <div className="card p-12 text-center max-w-md mx-auto mt-12 border border-slate-200">
        <div className="w-16 h-16 bg-primary-50 border border-primary-100 rounded-2xl flex items-center justify-center mx-auto mb-4 text-primary-600 shadow-xs">
          <FileQuestion className="w-8 h-8" />
        </div>
        <h2 className="text-2xl font-bold text-slate-900">404 - Page Not Found</h2>
        <p className="text-sm text-slate-500 mt-2 mb-6">
          The requested page does not exist, has been removed, or is temporarily unavailable.
        </p>
        <button
          onClick={() => navigate('/')}
          className="btn-primary inline-flex items-center gap-2"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Dashboard
        </button>
      </div>
    </Layout>
  );
};

export default NotFound;

import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Plane, ArrowLeft } from 'lucide-react';
import { Layout } from '../components/layout/Layout';

export const NotFound: React.FC = () => {
  const navigate = useNavigate();

  return (
    <Layout title="Page Not Found">
      <div className="card p-12 text-center max-w-lg mx-auto mt-12">
        <div className="w-16 h-16 bg-primary-50 rounded-2xl flex items-center justify-center mx-auto mb-4 text-primary-600">
          <Plane className="w-8 h-8" />
        </div>
        <h2 className="text-2xl font-bold text-slate-800">404 - Not Found</h2>
        <p className="text-sm text-slate-500 mt-2 mb-6">
          The requested page does not exist or has been moved.
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

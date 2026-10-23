import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Mail, ShieldCheck, ArrowRight, ArrowLeft, AlertCircle, CheckCircle, ExternalLink, Info } from 'lucide-react';
import authApi from '../api/auth';
import { LoadingSpinner } from '../components/ui/LoadingSpinner';

export const ForgotPassword: React.FC = () => {
  const [email, setEmail] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSuccess, setIsSuccess] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<{ email?: string }>({});
  const [devResetUrl, setDevResetUrl] = useState<string | null>(null);
  const [devNotice, setDevNotice] = useState<string | null>(null);

  useEffect(() => {
    if (isSuccess && import.meta.env.DEV) {
      authApi
        .getDevLatestResetLink(email.trim().toLowerCase())
        .then((res) => {
          if (res?.reset_url) {
            setDevResetUrl(res.reset_url);
          }
        })
        .catch((err: unknown) => {
          const resData = (err as { response?: { data?: { detail?: string } } })?.response?.data;
          const detail = resData?.detail || (err instanceof Error ? err.message : null);
          if (detail && typeof detail === 'string') {
            setDevNotice(detail);
          }
        });
    }
  }, [isSuccess, email]);

  const validate = (): boolean => {
    const errors: { email?: string } = {};
    const trimmedEmail = email.trim();

    if (!trimmedEmail) {
      errors.email = 'Email address is required.';
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmedEmail)) {
      errors.email = 'Please enter a valid email address.';
    }

    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage(null);
    setDevResetUrl(null);
    setDevNotice(null);

    if (!validate()) {
      return;
    }

    setIsSubmitting(true);
    try {
      await authApi.forgotPassword({
        email: email.trim().toLowerCase(),
      });
      setIsSuccess(true);
    } catch (err: unknown) {
      const message =
        err instanceof Error
          ? err.message
          : 'Unable to process password reset request. Please try again.';
      setErrorMessage(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col justify-center py-12 sm:px-6 lg:px-8">
      {/* Brand Header */}
      <div className="sm:mx-auto sm:w-full sm:max-w-md text-center">
        <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-primary-600 shadow-md shadow-primary-500/20 mb-4">
          <ShieldCheck className="w-6 h-6 text-white" />
        </div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">
          Reset Your Password
        </h1>
        <p className="mt-1.5 text-sm text-slate-600">
          Enter your email address to receive password reset instructions.
        </p>
      </div>

      {/* Card */}
      <div className="mt-8 sm:mx-auto sm:w-full sm:max-w-md px-4 sm:px-0">
        <div className="bg-white py-8 px-6 shadow-sm border border-slate-200 rounded-xl sm:px-10">
          {isSuccess ? (
            <div className="space-y-6 text-center">
              <div className="mx-auto flex items-center justify-center w-12 h-12 rounded-full bg-emerald-100 text-emerald-600">
                <CheckCircle className="w-6 h-6" />
              </div>
              <div>
                <h3 className="text-lg font-semibold text-slate-900">Check Your Email</h3>
                <p className="mt-2 text-sm text-slate-600 leading-relaxed">
                  If an account is associated with{' '}
                  <strong className="text-slate-900">{email}</strong>, we have sent instructions to
                  reset your password. Please check your inbox and spam folder.
                </p>
              </div>

              {/* Local Dev Helper Notice (active only during local development) */}
              {import.meta.env.DEV && devResetUrl && (
                <div className="p-4 bg-amber-50 border border-amber-200 rounded-lg text-left">
                  <div className="flex items-center gap-2 text-amber-800 font-semibold text-xs uppercase tracking-wider mb-1">
                    <span className="w-2 h-2 rounded-full bg-amber-500 animate-pulse"></span>
                    Local Development Reset Link
                  </div>
                  <p className="text-xs text-amber-700 mb-3">
                    SMTP is unconfigured in development. Click below to continue directly:
                  </p>
                  <a
                    href={devResetUrl}
                    className="inline-flex items-center justify-center gap-2 w-full py-2 px-3 bg-amber-600 hover:bg-amber-700 text-white text-xs font-medium rounded-md shadow-sm transition-colors"
                  >
                    <span>Proceed to Reset Password</span>
                    <ExternalLink className="w-3.5 h-3.5" />
                  </a>
                </div>
              )}

              {import.meta.env.DEV && !devResetUrl && devNotice && (
                <div className="p-4 bg-slate-50 border border-slate-200 rounded-lg text-left">
                  <div className="flex items-center gap-2 text-slate-700 font-semibold text-xs mb-1">
                    <Info className="w-4 h-4 text-slate-500" />
                    Local Development Notice
                  </div>
                  <p className="text-xs text-slate-600 leading-relaxed">
                    {devNotice}
                  </p>
                </div>
              )}

              <div className="pt-2">
                <Link
                  to="/login"
                  className="w-full flex items-center justify-center gap-2 py-2.5 px-4 border border-slate-300 rounded-lg shadow-sm text-sm font-medium text-slate-700 bg-white hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500 transition-colors"
                >
                  <ArrowLeft className="w-4 h-4" />
                  <span>Return to Sign In</span>
                </Link>
              </div>
            </div>
          ) : (
            <form className="space-y-5" onSubmit={handleSubmit} noValidate>
              {/* Error Banner */}
              {errorMessage && (
                <div
                  role="alert"
                  className="flex items-start gap-3 p-3.5 bg-red-50 border border-red-200 rounded-lg text-sm text-red-800"
                >
                  <AlertCircle className="w-5 h-5 text-red-600 shrink-0 mt-0.5" />
                  <div className="flex-1">
                    <span className="font-medium">Request failed: </span>
                    <span>{errorMessage}</span>
                  </div>
                </div>
              )}

              {/* Email Field */}
              <div>
                <label
                  htmlFor="reset-email-input"
                  className="block text-xs font-semibold uppercase tracking-wider text-slate-700 mb-1.5"
                >
                  Email Address
                </label>
                <div className="relative rounded-lg shadow-sm">
                  <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-400">
                    <Mail className="w-4 h-4" />
                  </div>
                  <input
                    id="reset-email-input"
                    name="email"
                    type="email"
                    autoComplete="email"
                    autoFocus
                    required
                    value={email}
                    onChange={(e) => {
                      setEmail(e.target.value);
                      if (fieldErrors.email) {
                        setFieldErrors((prev) => ({ ...prev, email: undefined }));
                      }
                    }}
                    placeholder="name@company.com"
                    className={`block w-full pl-9 pr-3 py-2 border rounded-lg text-sm bg-white placeholder-slate-400 focus:outline-none transition-colors ${
                      fieldErrors.email
                        ? 'border-red-300 focus:border-red-500 focus:ring-1 focus:ring-red-500'
                        : 'border-slate-300 focus:border-primary-500 focus:ring-1 focus:ring-primary-500'
                    }`}
                    aria-invalid={!!fieldErrors.email}
                    aria-describedby={fieldErrors.email ? 'reset-email-error' : undefined}
                  />
                </div>
                {fieldErrors.email && (
                  <p id="reset-email-error" className="mt-1 text-xs text-red-600">
                    {fieldErrors.email}
                  </p>
                )}
              </div>

              {/* Submit Button */}
              <div className="pt-2">
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="w-full flex items-center justify-center gap-2 py-2.5 px-4 border border-transparent rounded-lg shadow-sm text-sm font-medium text-white bg-primary-600 hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isSubmitting ? (
                    <>
                      <LoadingSpinner size="sm" className="border-t-white" />
                      <span>Sending instructions...</span>
                    </>
                  ) : (
                    <>
                      <span>Send Reset Link</span>
                      <ArrowRight className="w-4 h-4" />
                    </>
                  )}
                </button>
              </div>

              {/* Back to Login Link */}
              <div className="pt-3 text-center">
                <Link
                  to="/login"
                  className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-600 hover:text-slate-900 transition-colors"
                >
                  <ArrowLeft className="w-3.5 h-3.5" />
                  <span>Back to Sign In</span>
                </Link>
              </div>
            </form>
          )}

          {/* Secure System Notice */}
          <div className="mt-6 pt-5 border-t border-slate-100 text-center">
            <p className="text-xs text-slate-500">
              Anti-enumeration protection & rate limiting enforced.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ForgotPassword;

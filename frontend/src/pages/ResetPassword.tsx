import React, { useState, useEffect } from 'react';
import { useNavigate, useSearchParams, Link } from 'react-router-dom';
import { Lock, Eye, EyeOff, ShieldCheck, ArrowRight, ArrowLeft, AlertCircle, CheckCircle } from 'lucide-react';
import authApi from '../api/auth';
import { LoadingSpinner } from '../components/ui/LoadingSpinner';

export const ResetPassword: React.FC = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token') || '';

  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSuccess, setIsSuccess] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<{
    newPassword?: string;
    confirmPassword?: string;
  }>({});
  const [countdown, setCountdown] = useState(5);

  // Auto redirect on success
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    if (isSuccess && countdown > 0) {
      timer = setTimeout(() => {
        setCountdown((prev) => prev - 1);
      }, 1000);
    } else if (isSuccess && countdown === 0) {
      navigate('/login', { replace: true });
    }
    return () => clearTimeout(timer);
  }, [isSuccess, countdown, navigate]);

  const validate = (): boolean => {
    const errors: { newPassword?: string; confirmPassword?: string } = {};

    if (!newPassword) {
      errors.newPassword = 'Password is required.';
    } else if (newPassword.length < 8) {
      errors.newPassword = 'Password must be at least 8 characters.';
    }

    if (!confirmPassword) {
      errors.confirmPassword = 'Please confirm your password.';
    } else if (newPassword !== confirmPassword) {
      errors.confirmPassword = 'Passwords do not match.';
    }

    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage(null);

    if (!validate()) {
      return;
    }

    setIsSubmitting(true);
    try {
      await authApi.resetPassword({
        token,
        new_password: newPassword,
      });
      setIsSuccess(true);
    } catch (err: unknown) {
      const message =
        err instanceof Error
          ? err.message
          : 'Failed to reset password. The link may be expired or already used.';
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
          Create New Password
        </h1>
        <p className="mt-1.5 text-sm text-slate-600">
          Enter and confirm your new secure password.
        </p>
      </div>

      {/* Card */}
      <div className="mt-8 sm:mx-auto sm:w-full sm:max-w-md px-4 sm:px-0">
        <div className="bg-white py-8 px-6 shadow-sm border border-slate-200 rounded-xl sm:px-10">
          {!token ? (
            <div className="space-y-6 text-center">
              <div className="mx-auto flex items-center justify-center w-12 h-12 rounded-full bg-amber-100 text-amber-600">
                <AlertCircle className="w-6 h-6" />
              </div>
              <div>
                <h3 className="text-lg font-semibold text-slate-900">Invalid or Missing Token</h3>
                <p className="mt-2 text-sm text-slate-600 leading-relaxed">
                  The password reset link is invalid or incomplete. Please request a new password reset link.
                </p>
              </div>
              <div className="pt-2">
                <Link
                  to="/forgot-password"
                  className="w-full flex items-center justify-center gap-2 py-2.5 px-4 border border-transparent rounded-lg shadow-sm text-sm font-medium text-white bg-primary-600 hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500 transition-colors"
                >
                  <span>Request New Reset Link</span>
                  <ArrowRight className="w-4 h-4" />
                </Link>
              </div>
            </div>
          ) : isSuccess ? (
            <div className="space-y-6 text-center">
              <div className="mx-auto flex items-center justify-center w-12 h-12 rounded-full bg-emerald-100 text-emerald-600">
                <CheckCircle className="w-6 h-6" />
              </div>
              <div>
                <h3 className="text-lg font-semibold text-slate-900">Password Reset Successful</h3>
                <p className="mt-2 text-sm text-slate-600 leading-relaxed">
                  Your password has been securely updated. You will be redirected to the sign in page in{' '}
                  <strong className="text-slate-900">{countdown}</strong> seconds.
                </p>
              </div>
              <div className="pt-2">
                <Link
                  to="/login"
                  className="w-full flex items-center justify-center gap-2 py-2.5 px-4 border border-transparent rounded-lg shadow-sm text-sm font-medium text-white bg-primary-600 hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500 transition-colors"
                >
                  <span>Sign In Now</span>
                  <ArrowRight className="w-4 h-4" />
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
                    <span className="font-medium">Reset failed: </span>
                    <span>{errorMessage}</span>
                    {(errorMessage.toLowerCase().includes('expired') ||
                      errorMessage.toLowerCase().includes('already been used') ||
                      errorMessage.toLowerCase().includes('invalid')) && (
                      <div className="mt-2">
                        <Link
                          to="/forgot-password"
                          className="font-medium underline hover:text-red-900"
                        >
                          Request a new reset link &rarr;
                        </Link>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* New Password Field */}
              <div>
                <label
                  htmlFor="new-password-input"
                  className="block text-xs font-semibold uppercase tracking-wider text-slate-700 mb-1.5"
                >
                  New Password
                </label>
                <div className="relative rounded-lg shadow-sm">
                  <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-400">
                    <Lock className="w-4 h-4" />
                  </div>
                  <input
                    id="new-password-input"
                    name="newPassword"
                    type={showPassword ? 'text' : 'password'}
                    autoComplete="new-password"
                    autoFocus
                    required
                    value={newPassword}
                    onChange={(e) => {
                      setNewPassword(e.target.value);
                      if (fieldErrors.newPassword) {
                        setFieldErrors((prev) => ({ ...prev, newPassword: undefined }));
                      }
                    }}
                    placeholder="••••••••••••"
                    className={`block w-full pl-9 pr-10 py-2 border rounded-lg text-sm bg-white placeholder-slate-400 focus:outline-none transition-colors ${
                      fieldErrors.newPassword
                        ? 'border-red-300 focus:border-red-500 focus:ring-1 focus:ring-red-500'
                        : 'border-slate-300 focus:border-primary-500 focus:ring-1 focus:ring-primary-500'
                    }`}
                    aria-invalid={!!fieldErrors.newPassword}
                    aria-describedby={fieldErrors.newPassword ? 'new-password-error' : undefined}
                  />
                  <button
                    type="button"
                    tabIndex={-1}
                    onClick={() => setShowPassword(!showPassword)}
                    aria-label={showPassword ? 'Hide password' : 'Show password'}
                    className="absolute inset-y-0 right-0 pr-3 flex items-center text-slate-400 hover:text-slate-600 transition-colors"
                  >
                    {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
                {fieldErrors.newPassword ? (
                  <p id="new-password-error" className="mt-1 text-xs text-red-600">
                    {fieldErrors.newPassword}
                  </p>
                ) : (
                  <p className="mt-1 text-xs text-slate-500">Minimum 8 characters</p>
                )}
              </div>

              {/* Confirm Password Field */}
              <div>
                <label
                  htmlFor="confirm-password-input"
                  className="block text-xs font-semibold uppercase tracking-wider text-slate-700 mb-1.5"
                >
                  Confirm New Password
                </label>
                <div className="relative rounded-lg shadow-sm">
                  <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-400">
                    <Lock className="w-4 h-4" />
                  </div>
                  <input
                    id="confirm-password-input"
                    name="confirmPassword"
                    type={showConfirmPassword ? 'text' : 'password'}
                    autoComplete="new-password"
                    required
                    value={confirmPassword}
                    onChange={(e) => {
                      setConfirmPassword(e.target.value);
                      if (fieldErrors.confirmPassword) {
                        setFieldErrors((prev) => ({ ...prev, confirmPassword: undefined }));
                      }
                    }}
                    placeholder="••••••••••••"
                    className={`block w-full pl-9 pr-10 py-2 border rounded-lg text-sm bg-white placeholder-slate-400 focus:outline-none transition-colors ${
                      fieldErrors.confirmPassword
                        ? 'border-red-300 focus:border-red-500 focus:ring-1 focus:ring-red-500'
                        : 'border-slate-300 focus:border-primary-500 focus:ring-1 focus:ring-primary-500'
                    }`}
                    aria-invalid={!!fieldErrors.confirmPassword}
                    aria-describedby={fieldErrors.confirmPassword ? 'confirm-password-error' : undefined}
                  />
                  <button
                    type="button"
                    tabIndex={-1}
                    onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                    aria-label={showConfirmPassword ? 'Hide password' : 'Show password'}
                    className="absolute inset-y-0 right-0 pr-3 flex items-center text-slate-400 hover:text-slate-600 transition-colors"
                  >
                    {showConfirmPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
                {fieldErrors.confirmPassword && (
                  <p id="confirm-password-error" className="mt-1 text-xs text-red-600">
                    {fieldErrors.confirmPassword}
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
                      <span>Updating password...</span>
                    </>
                  ) : (
                    <>
                      <span>Reset Password</span>
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
              Single-use cryptographic validation enforced.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ResetPassword;


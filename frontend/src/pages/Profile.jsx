import React, { useEffect, useState } from "react";
import { Camera, Pencil } from "lucide-react";
import PageHeader from "../components/PageHeader";
import { useTranslation } from "react-i18next";
import AuthService from "../services/auth.service";
import ProfileService from "../services/profile.service";
import { Input, Form, Modal, ModalBody, ModalFooter } from "reactstrap";
import "../Styles/Profil.css";
import { getRoleDisplayName } from '../utils/permissions';
import { isDemoUser } from '../utils/demo';

function Profile() {
  const { t } = useTranslation();
  const BACKEND_HOST = import.meta.env.VITE_BASE_URL;
  const [image, setImage] = useState(JSON.parse(localStorage.getItem('user')).avatar);
  const [user, setUser] = useState(null);
  const [isEditing, setIsEditing] = useState(false);
  const [passwordChanged, setPasswordChanged] = useState(null);
  const [formData, setFormData] = useState({
    first_name: "",
    last_name: "",
    email: "",
    phone: "",
    avatar: "",
  });
  const [errors, setErrors] = useState({
    email: "",
    phone: ""
  });
  const [modal, setModal] = useState(false);
  const [unmountOnClose, setUnmountOnClose] = useState(true);
  const toggle = () => setModal(!modal);
  const [data, setData] = useState({
    old_password: "",
    new_password: "",
    new_password_copy: "",
  });
  const [imageError, setImageError] = useState(false);

  useEffect(() => {
    setImageError(false);
  }, [formData.avatar]);

  const validateEmail = (email) => {
    const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return re.test(String(email).toLowerCase());
  };

  const validatePhone = (phone) => {
    return phone.length === 8 && /^\d+$/.test(phone);
  };

  const handleChange = (e) => {
    const { id, value } = e.target;
    setData((prevState) => ({ ...prevState, [id]: value }));
  };

  const handleInputChange = (e) => {
    const { id, value } = e.target;
    setFormData({ ...formData, [id]: value });

    if (isEditing) {
      if (id === 'email') {
        setErrors({
          ...errors,
          email: value && !validateEmail(value) ? t('profile.invalidEmail') : ""
        });
      }
      if (id === 'phone') {
        setErrors({
          ...errors,
          phone: value && !validatePhone(value) ? t('profile.phoneDigits') : ""
        });
      }
    }
  };

  const handleEditButtonClick = () => {
    setIsEditing(true);
  };

  const handleSaveButtonClick = () => {
    const emailValid = !formData.email || validateEmail(formData.email);
    const phoneValid = !formData.phone || validatePhone(formData.phone);

    if (!emailValid || !phoneValid) {
      setErrors({
        email: !emailValid ? t('profile.invalidEmail') : "",
        phone: !phoneValid ? t('profile.phoneDigits') : ""
      });
      return;
    }

    ProfileService.update(AuthService.getUser()._id, formData)
      .then((res) => {
        setUser(res.data);
        setFormData(res.data);
        setIsEditing(false);
        // Update localStorage so navbar and other components reflect the change
        const currentUser = JSON.parse(localStorage.getItem('user') || '{}');
        localStorage.setItem('user', JSON.stringify({ ...currentUser, ...res.data }));
      })
      .catch((err) => {
        console.error("Error:", err);
      });
  };

  const handleAvatarChange = (e) => {
    const file = e.target.files[0];

    if (!file) {
      console.error('No file selected');
      return;
    }

    e.target.value = '';
    const upload = new FormData();
    upload.append('avatar', file);

    ProfileService.uploadAvatar(upload)
      .then((response) => setAvatar(response.data.avatar))
      .catch((error) => {
        console.error('Error uploading avatar:', error);
      });
  };

  const handleAvatarRemove = () => {
    ProfileService.removeAvatar()
      .then(() => setAvatar(null))
      .catch((error) => {
        console.error('Error removing avatar:', error);
      });
  };

  // Keep the page, the stored user and the top bar in step.
  const setAvatar = (avatar) => {
    setFormData((prev) => ({ ...prev, avatar }));
    try {
      const currentUser = JSON.parse(localStorage.getItem('user') || '{}');
      localStorage.setItem('user', JSON.stringify({ ...currentUser, avatar }));
    } catch {
      // Storage unavailable: the top bar still updates from the event.
    }
    window.dispatchEvent(new CustomEvent('serops:user-updated', { detail: { avatar } }));
  };

  useEffect(() => {
    ProfileService.getOne(AuthService.getUser()._id)
      .then((res) => {
        setUser(res.data);
        setFormData(res.data);
      })
      .catch((err) => {
        console.error("Error:", err);
      });
  }, []);

  const handlePassword = async (e) => {
    e.preventDefault();

    try {
      await ProfileService.resetPassword(data);
      setPasswordChanged(true);
    } catch (error) {
      console.error("Error:", error.response.data.error);
      setPasswordChanged(false);
    } finally {
      toggle();
    }
  };

  const initials = `${(formData.first_name || '').charAt(0)}${(formData.last_name || '').charAt(0)}`.toUpperCase() || 'U';
  const field = (id, label, props = {}, error) => (
    <div className="profile-field">
      <label htmlFor={id} className="form-label">{label}</label>
      <Input className="form-control" id={id} {...props} />
      {error && <div className="profile-field-error">{error}</div>}
    </div>
  );

  return (
    <div className="profile-page">
      <PageHeader
        title={t('profile.title')}
        actions={
          isEditing ? (
            <button className="btn btn-primary" type="button" onClick={handleSaveButtonClick}>{t('common.save')}</button>
          ) : (
            <button className="btn btn-secondary" type="button" onClick={handleEditButtonClick}>
              <Pencil size={14} aria-hidden="true" /> {t('common.edit')}
            </button>
          )
        }
      />

      {passwordChanged === true && (
        <div className="alert alert-success" role="status">{t('profile.passwordUpdated')}</div>
      )}
      {passwordChanged === false && (
        <div className="alert alert-danger" role="alert">{t('profile.passwordUpdateFailed')}</div>
      )}

      <section className="ds-settings-section">
        <div className="ds-settings-section-body">
          <div className="profile-identity">
            <div className="profile-avatar">
              {!imageError && formData.avatar ? (
                <img src={`${BACKEND_HOST}${formData.avatar}`} alt="" onError={() => setImageError(true)} />
              ) : (
                <span aria-hidden="true">{initials}</span>
              )}
              <label className="profile-avatar-edit" htmlFor="avatar" title={t('profile.changePhoto')}>
                <input type="file" id="avatar" accept="image/*" className="visually-hidden" onChange={handleAvatarChange} />
                <Camera size={14} aria-hidden="true" />
                <span className="visually-hidden">{t('profile.changePhoto')}</span>
              </label>
            </div>
            <div className="profile-identity-text">
              <div className="profile-name">{`${formData.first_name || ''} ${formData.last_name || ''}`.trim() || formData.email}</div>
              <div className="profile-email">{formData.email}</div>
              {formData.avatar && (
                <button type="button" className="btn btn-link btn-sm p-0" onClick={handleAvatarRemove}>
                  {t('profile.removePhoto')}
                </button>
              )}
              <span className="badge ds-chip ds-chip-neutral">
                {isDemoUser() ? t('profile.demoRole') : getRoleDisplayName(formData.role)}
              </span>
            </div>
          </div>

          <Form className="profile-grid" onSubmit={(e) => e.preventDefault()}>
            {field('first_name', t('profile.firstName'), { type: 'text', value: formData.first_name, onChange: handleInputChange, disabled: !isEditing })}
            {field('last_name', t('profile.lastName'), { type: 'text', value: formData.last_name, onChange: handleInputChange, disabled: !isEditing })}
            {field('email', t('profile.emailAddress'), { type: 'email', value: formData.email, onChange: handleInputChange, disabled: !isEditing }, isEditing && errors.email)}
            {field('phone', t('profile.phoneNumber'), { type: 'text', value: formData.phone, onChange: handleInputChange, disabled: !isEditing, maxLength: 8 }, isEditing && errors.phone)}
          </Form>
        </div>
      </section>

      <section className="ds-settings-section">
        <header className="ds-settings-section-head">
          <div className="ds-settings-section-text">
            <h2 className="ds-settings-section-title">{t('profile.password')}</h2>
            <p className="ds-settings-section-desc">{t('profile.passwordDesc')}</p>
          </div>
          <div className="ds-settings-section-actions">
            <button className="btn btn-secondary" type="button" onClick={toggle}>{t('profile.updatePassword')}</button>
          </div>
        </header>
      </section>

      <Modal isOpen={modal} toggle={toggle} unmountOnClose={unmountOnClose}>
        <ModalBody>
          <h2 className="modal-title h5 mb-3">{t('profile.updatePassword')}</h2>
          <Form onSubmit={(e) => e.preventDefault()} className="d-flex flex-column gap-3">
            {field('old_password', t('profile.oldPassword'), { type: 'password', value: data.old_password, onChange: handleChange, autoComplete: 'current-password' })}
            {field('new_password', t('profile.newPassword'), { type: 'password', value: data.new_password, onChange: handleChange, autoComplete: 'new-password' })}
            {field('new_password_copy', t('profile.repeatPassword'), { type: 'password', value: data.new_password_copy, onChange: handleChange, autoComplete: 'new-password' })}
          </Form>
        </ModalBody>
        <ModalFooter>
          <button type="button" className="btn btn-secondary" onClick={toggle}>{t('common.cancel')}</button>
          <button type="button" className="btn btn-primary" onClick={handlePassword}>{t('common.submit')}</button>
        </ModalFooter>
      </Modal>
    </div>
  );
}

export default Profile;
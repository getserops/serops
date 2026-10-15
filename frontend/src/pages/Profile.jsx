import React, { useEffect, useState } from "react";
import { FaCamera } from "react-icons/fa";
import { useTranslation } from "react-i18next";
import AuthService from "../services/auth.service";
import ProfileService from "../services/profile.service";
import {
  Card,
  Input,
  Form,
  Row,
  Col,
  Container,
  Modal,
  ModalBody,
  ModalFooter,
  Badge,
} from "reactstrap";
import "../Styles/Profil.css";
import { Icon } from "@iconify/react";
import { useMediaQuery } from '@mui/material';
import { Space, Alert } from 'antd';
import { getRoleDisplayName, getRoleColor } from '../utils/permissions';
import { isDemoUser } from '../utils/demo';

function Profile() {
  const { t } = useTranslation();
  const BACKEND_HOST = import.meta.env.VITE_BASE_URL;
  const [image, setImage] = useState(JSON.parse(localStorage.getItem('user')).avatar);
  const isSmallScreen = useMediaQuery("(max-width: 767px)");
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

    const formData = new FormData();
    formData.append('avatar', file);

    ProfileService.uploadAvatar(formData)
      .then((response) => {
      })
      .catch((error) => {
        console.error('Error uploading avatar:', error);
      });
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

  return (
    <div>

      {passwordChanged && (
        <Space direction="vertical" style={{ width: "40%" }}>
          <Alert
            message={t('common.success')}
            description={t('profile.passwordUpdated')}
            type="success"
            showIcon
            closable
          />
        </Space>
      )}

      {/* Display error message */}
      {passwordChanged === false && (
        <Space direction="vertical" style={{ width: "40%" }}>
          <Alert
            message={t('common.error')}
            description={t('profile.passwordUpdateFailed')}
            type="error"
            showIcon
            closable
          />
        </Space>
      )}

      <Container className="container-project mt-5">
        <Row className="row1 mx-auto">
          <Col className="text-start">

          </Col>
        </Row>

        <Row className="row2 mt-2">
          <Col lg="6" md="6" sm="12" xs="12" className="mx-auto">
            <Card className="card-profil p-5" style={{ borderRadius: "5%" }}>
              <div className="circle-avatar" style={{ position: "relative", width: "150px", height: "150px", margin: "0 auto" }}>
                <div className="image-avatar" style={{ width: "100%", height: "100%", borderRadius: "50%", overflow: "hidden", border: "4px solid #fff", boxShadow: "0 0 20px rgba(0,0,0,0.1)" }}>
                  <img
                    className="img-pro"
                    src={
                      !imageError && formData.avatar
                        ? `${BACKEND_HOST}${formData.avatar}`
                        : `https://ui-avatars.com/api/?name=${(formData.first_name || 'User')}+${(formData.last_name || '')}&background=random&size=150`
                    }
                    alt="Profile"
                    style={{ width: "100%", height: "100%", objectFit: "cover" }}
                    onError={() => setImageError(true)}
                  />
                  <label className="camera-icon" htmlFor="avatar" style={{
                    position: "absolute",
                    bottom: "10px",
                    right: "10px",
                    background: "#2B47D6",
                    color: "white",
                    width: "35px",
                    height: "35px",
                    borderRadius: "50%",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    cursor: "pointer",
                    boxShadow: "0 2px 5px rgba(0,0,0,0.2)"
                  }}>
                    <input
                      type="file"
                      id="avatar"
                      accept="image/*"
                      style={{ display: "none" }}
                      onChange={handleAvatarChange}
                    />
                    <FaCamera size={16} />
                  </label>
                </div>
              </div>

              <div className="card-body mt-2 w-100">
                <Form style={{ marginTop: "5%" }}>
                  <div className="mb-4">
                    <label htmlFor="first_name" className="form-label">
                      {t('profile.firstName')}
                    </label>
                    <Input
                      className="form-control"
                      type="text"
                      id="first_name"
                      value={formData.first_name}
                      onChange={handleInputChange}
                      disabled={!isEditing}
                    />
                  </div>

                  <div className="mb-4">
                    <label htmlFor="last_name" className="form-label">
                      {t('profile.lastName')}
                    </label>
                    <Input
                      className="form-control"
                      type="text"
                      id="last_name"
                      value={formData.last_name}
                      onChange={handleInputChange}
                      disabled={!isEditing}
                    />
                  </div>

                  <div className="mb-4">
                    <label htmlFor="email" className="form-label">
                      {t('profile.emailAddress')}
                    </label>
                    <Input
                      className="form-control"
                      type="email"
                      id="email"
                      value={formData.email}
                      onChange={handleInputChange}
                      disabled={!isEditing}
                    />
                    {isEditing && errors.email && (
                      <div className="text-danger" style={{ fontSize: "0.8rem" }}>
                        {errors.email}
                      </div>
                    )}
                  </div>

                  <div className="mb-2">
                    <label htmlFor="phone" className="form-label">
                      {t('profile.phoneNumber')}
                    </label>
                    <Input
                      className="form-control"
                      type="text"
                      id="phone"
                      value={formData.phone}
                      onChange={handleInputChange}
                      disabled={!isEditing}
                      maxLength={8}
                    />
                    {isEditing && errors.phone && (
                      <div className="text-danger" style={{ fontSize: "0.8rem" }}>
                        {errors.phone}
                      </div>
                    )}
                  </div>

                  {/* Role Display (Read-only) */}
                  <div className="mb-4">
                    <label className="form-label" htmlFor="profile-role">{t('profile.role')}</label>
                    <Input
                      id="profile-role"
                      className="form-control"
                      type="text"
                      value={isDemoUser() ? t('profile.demoRole') : getRoleDisplayName(formData.role)}
                      disabled={true}
                    />
                  </div>

                  <div className="d-flex justify-content-end position-relative">
                    {!isEditing && (
                      <button
                        className="btn text-center"
                        type="button"
                        style={{ cursor: "pointer" }}
                        onClick={handleEditButtonClick}
                      >
                        <Icon icon="fluent:edit-24-filled" />
                        {t('common.edit')}
                      </button>
                    )}
                    {isEditing && (
                      <button
                        className="btn text-center"
                        type="button"
                        onClick={handleSaveButtonClick}
                      >
                        {t('common.save')}
                      </button>
                    )}
                  </div>
                </Form>

                {/* Bouton "Update Password" déplacé ici */}
                <div className="text-end mt-3">
                  <button className="btn-update-password" onClick={toggle}>
                    <i>
                      <Icon icon="fluent:edit-24-filled" />
                    </i>
                    {isSmallScreen ? "" : t('profile.updatePassword')}
                  </button>
                </div>
              </div>
            </Card>
          </Col>
        </Row>

        <Modal
          className="model mt-0"
          isOpen={modal}
          toggle={toggle}
          unmountOnClose={unmountOnClose}
        >
          <ModalBody className="model-body mt-0">
            <Form>
              <div className="mb-2">
                <label htmlFor="old_password" className="form-label">
                  {t('profile.oldPassword')}
                </label>
                <Input
                  className="form-control"
                  type="password"
                  id="old_password"
                  value={data.old_password}
                  onChange={handleChange}
                />
              </div>
              <div className="mb-2">
                <label htmlFor="new_password" className="form-label">
                  {t('profile.newPassword')}
                </label>
                <Input
                  className="form-control"
                  type="password"
                  id="new_password"
                  value={data.new_password}
                  onChange={handleChange}
                />
              </div>
              <div className="mb-2">
                <label htmlFor="new_password_copy" className="form-label">
                  {t('profile.repeatPassword')}
                </label>
                <Input
                  className="form-control"
                  type="password"
                  id="new_password_copy"
                  value={data.new_password_copy}
                  onChange={handleChange}
                />
              </div>

              <ModalFooter className="form-btn">
                <button
                  className="cancel-button"
                  onClick={toggle}
                  style={{
                    backgroundColor: "#ccc",
                    color: "black",
                    border: "none",
                    padding: "10px 20px",
                    borderRadius: "5px",
                    cursor: "pointer",
                    fontSize: "16px",
                  }}
                >
                  {t('common.cancel')}
                </button>

                <button
                  className="submit-button"
                  onClick={handlePassword}
                  style={{
                    backgroundColor: "#2B47D6",
                    color: "white",
                    border: "none",
                    padding: "10px 20px",
                    borderRadius: "5px",
                    cursor: "pointer",
                    fontSize: "16px",
                  }}
                >
                  {t('common.submit')}
                </button>
              </ModalFooter>
            </Form>
          </ModalBody>
        </Modal>
      </Container>
    </div>
  );
}

export default Profile;
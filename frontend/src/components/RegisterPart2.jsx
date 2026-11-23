import React, { useState } from 'react';
import { Col, Form} from "react-bootstrap";
import { useTranslation } from "react-i18next";


function RegisterPart2({ formData, setFormData }) {
  const { t } = useTranslation();
  const [isPasswordValid, setIsPasswordValid] = useState(true);
  const [isConfirmPasswordValid, setIsConfirmPasswordValid] = useState(true);

  const handlePasswordChange = (e) => {
    const { value } = e.target;
    setFormData((prevFormData) => ({
      ...prevFormData,
      user: {
        ...prevFormData.user,
        password: value,
      },
    }));
    validatePassword(value);
  };

  const handleConfirmPasswordChange = (e) => {
    const { value } = e.target;
    setFormData((prevFormData) => ({
      ...prevFormData,
      user: {
        ...prevFormData.user,
        password_confirmation: value,
      },
    }));
    validateConfirmPassword(value);
  };

  const validatePassword = (password) => {
    const regex = /^(?=.*\d)(?=.*[a-z])(?=.*[A-Z]).{10,}$/;
    setIsPasswordValid(regex.test(password));
  };

  const validateConfirmPassword = (confirmPassword) => {
    setIsConfirmPasswordValid(formData.user.password === confirmPassword);
  };

  return (
    
      <Col className=""> 
      <Form autoComplete="off" className='register1-frame'>

        <Form.Group className="form-field "  >
          <Form.Label htmlFor="password" className="form-label">
            {t('auth.password')}
          </Form.Label>
          <Form.Control
            className={`form-control ${isPasswordValid? '' : 'border border-danger'}`}
           style={{ backgroundColor: isPasswordValid ? "" : "#ffeded" }}
            type="password"
            id="password"
            required
            placeholder={t('login.passwordPlaceholder')}
            value={formData.user.password}
            onChange={handlePasswordChange}
            onBlur={() => validatePassword(formData.user.password)}
          />
          {!isPasswordValid && (
            <p className="text-danger mt-1" style={{ wordWrap: 'break-word' , maxWidth: '300px'}} >
              {t('registerPart2.passwordRule')}
            </p>
          )}
        </Form.Group>


        <Form.Group className={`form-field ${isPasswordValid ? 'mt-3' : ''}`}>
          <Form.Label htmlFor="confirmPassword" className="form-label">
            {t('registerPart2.repeatPassword')}
          </Form.Label>
          <Form.Control
            className={`form-control ${isConfirmPasswordValid ? '' : 'border border-danger'}`}
            style={{ backgroundColor : isConfirmPasswordValid ? "" : "#ffeded"}}
            type="password"
            id="password_confirmation"
            required
            placeholder={t('registerPart2.repeatPassword')}
            value={formData.user.password_confirmation}
            onChange={handleConfirmPasswordChange}
            onBlur={() => validateConfirmPassword(formData.user.password_confirmation)}
          />
          {!isConfirmPasswordValid && (
            <p className="text-danger mt-1">{t('registerPart2.passwordsMismatch')}</p>
          )}
        </Form.Group>

      </Form>
      </Col>
    
  );
}

export default RegisterPart2;

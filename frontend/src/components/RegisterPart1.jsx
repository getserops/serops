import React, { useEffect, useState } from 'react';
import { Col, Form } from "react-bootstrap";

function RegisterPart1({ formData, setFormData }) {
  const [formErrors, setFormErrors] = useState({});
  const [isFormComplete, setIsFormComplete] = useState(false);

  const handleInputChange = (e) => {
    const { name, value } = e.target;
    setFormData((prevFormData) => ({
      ...prevFormData,
      user: {
        ...prevFormData.user,
        [name]: value,
      },
    }));
  };

  const handleInputBlur = (e) => {
    const { name, value } = e.target;

    if (!value.trim()) {
      setFormErrors((prevErrors) => ({
        ...prevErrors,
        [name]: 'This field is required',
      }));
    } else if (name === 'phone') {
      // Validation spécifique pour le champ "phone"
      const phoneRegex = /^\d{8}$/;
      if (!phoneRegex.test(value)) {
        setFormErrors((prevErrors) => ({
          ...prevErrors,
          [name]: 'Phone number must be exactly 8 digits',
        }));
      } else {
        setFormErrors((prevErrors) => ({
          ...prevErrors,
          [name]: '',
        }));
      }
    } else {
      setFormErrors((prevErrors) => ({
        ...prevErrors,
        [name]: '',
      }));
    }
  };

  const isFormValid = () => {
    // Check if all required fields are filled
    const requiredFields = ['first_name', 'last_name', 'email', 'phone', 'organisation'];
    for (const field of requiredFields) {
      if (!formData.user[field] || !formData.user[field].trim()) {
        return false;
      }
    }
    return true;
  };

  useEffect(() => {
    setIsFormComplete(isFormValid());
  }, [formData]);

  return (
    <Col className="">
      <Form className='register1-frame'>
        <Form.Group className="form-field ">
          <Form.Label htmlFor="first_name" className="form-label">
            First name
          </Form.Label>
          <Form.Control
            className={`form-control ${formErrors.first_name ? 'is-invalid' : ''}`}
            style={{ backgroundColor: formErrors.first_name ? "#ffeded" : "" }}
            type="text"
            id="first_name"
            name="first_name"
            required
            placeholder="Enter your first name"
            value={formData.user.first_name}
            onChange={handleInputChange}
            onBlur={handleInputBlur}
          />
          {formErrors.first_name && <div className="invalid-feedback">{formErrors.first_name}</div>}
        </Form.Group>

        <Form.Group className="form-field ">
          <Form.Label htmlFor="last_name" className="form-label">
            Last name
          </Form.Label>
          <Form.Control
            className={`form-control ${formErrors.last_name ? 'is-invalid' : ''}`}
            style={{ backgroundColor: formErrors.last_name ? "#ffeded" : "" }}
            type="text"
            id="last_name"
            name="last_name"
            required
            placeholder="Enter your last name"
            value={formData.user.last_name}
            onChange={handleInputChange}
            onBlur={handleInputBlur}
          />
          {formErrors.last_name && <div className="invalid-feedback">{formErrors.last_name}</div>}
        </Form.Group>

        <Form.Group className="form-field ">
          <Form.Label htmlFor="emailaddress" className="form-label">
            Email address
          </Form.Label>
          <Form.Control
            className={`form-control ${formErrors.email ? 'is-invalid' : ''}`}
            style={{ backgroundColor: formErrors.email ? "#ffeded" : "" }}
            type="email"
            id="email"
            name="email"
            required
            placeholder="Enter your email"
            value={formData.user.email}
            onChange={handleInputChange}
            onBlur={handleInputBlur}
          />
          {formErrors.email && <div className="invalid-feedback">{formErrors.email}</div>}
        </Form.Group>

        <Form.Group className="form-field ">
          <Form.Label htmlFor="organisation" className="form-label">
            Company name
          </Form.Label>
          <Form.Control
            className="form-control"
            type="text"
            id="organisation"
            name="organisation"
            required
            placeholder="Enter your company name"
            value={formData.organisation.name}
            onChange={(e) => {
              setFormData((prevFormData) => ({
                ...prevFormData,
                organisation: {
                  ...prevFormData.organisation,
                  name: e.target.value,
                },
              }));
            }}
          />
        </Form.Group>

        <Form.Group className="form-field ">
          <Form.Label htmlFor="phone" className="form-label">
            Phone Number
          </Form.Label>
          <Form.Control
            className={`form-control ${formErrors.phone ? 'is-invalid' : ''}`}
            style={{ backgroundColor: formErrors.phone ? "#ffeded" : "" }}
            type="text"
            id="phone"
            name="phone"
            required
            placeholder="+216 | Enter your Phone Number"
            value={formData.user.phone}
            onChange={handleInputChange}
            onBlur={handleInputBlur}
          />
          {formErrors.phone && <div className="invalid-feedback">{formErrors.phone}</div>}
        </Form.Group>
      </Form>
    </Col>
  );
}

export default RegisterPart1;
package com.example.demo.entity;

import jakarta.persistence.*;
import java.util.List;

@Entity
public class Course {
    
    @Id
    @GeneratedValue(strategy = GenerationType.AUTO)
    private Long courseId;


    private String courseName;
    
    private String courseDescription;


    @OneToMany(mappedBy = "course")
    private List<Cohort> cohorts;

    public Course() {
    }
    
    public Course(String courseName, String courseDescription) {
        this.courseName = courseName;
        this.courseDescription = courseDescription;

    }
    
    public Long getCourseId() {
        return courseId;
    }
    
    public void setCourseId(Long courseId) {
        this.courseId = courseId;
    }
    
    public String getCourseName() {
        return courseName;
    }
    
    public void setCourseName(String courseName) {
        this.courseName = courseName;
    }
    
    public String getCourseDescription() {
        return courseDescription;
    }
    
    public void setCourseDescription(String courseDescription) {
        this.courseDescription = courseDescription;
    }

}

